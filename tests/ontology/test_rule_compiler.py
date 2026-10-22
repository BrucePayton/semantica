"""Semantic and pipeline tests for schema-to-Horn compilation (no LLM network)."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from semantica.ontology import (
    OntologyEngine, OntologyRuleCompiler, OntologyRuleCompilationError,
    LLMOntologyGenerator,
)
from semantica.reasoning import Reasoner


def schema():
    return {
        "uri": "https://example.org/hr#",
        "classes": [
            {"name": "Employee", "uri": "https://example.org/hr#Employee", "parent": "Person"},
            {"name": "Person"}, {"name": "Organization"},
        ],
        "properties": [
            {"name": "worksFor", "type": "object", "domain": ["Employee"],
             "range": ["Organization"]},
            {"name": "name", "type": "data", "domain": ["Person"], "range": ["xsd:string"]},
        ],
    }


def run(ontology, facts):
    reasoner = Reasoner()
    compiled = OntologyRuleCompiler().load(ontology, reasoner)
    results = reasoner.infer_with_results(facts)
    return compiled, reasoner, results


def test_domain_range_and_multi_hop_inheritance():
    original = schema()
    saved = deepcopy(original)
    compiled, reasoner, results = run(original, ["worksFor(Alice, Acme)"])
    assert {"Employee(Alice)", "Person(Alice)", "Organization(Acme)"} <= reasoner.facts
    assert "worksFor(Acme, Alice)" not in reasoner.facts
    assert original == saved
    assert all(r.rule_used.metadata["axioms"] and r.premises for r in results)
    assert all(r.rule_used.metadata["ontology"] == original["uri"] for r in results)
    json.dumps(compiled.to_dict())


def test_named_aliases_multiple_superclasses_and_domains():
    ontology = schema()
    ontology["classes"][0]["subClassOf"] = ["Person", "Organization"]
    ontology["properties"][0]["domain"] = ["https://example.org/hr#Employee", "Person"]
    _, reasoner, _ = run(ontology, ["worksFor(Alice, Acme)"])
    assert {"Person(Alice)", "Organization(Alice)"} <= reasoner.facts


def test_domain_is_not_a_requirement_or_reverse_rule():
    _, reasoner, results = run(schema(), ["Employee(Alice)", "Organization(Acme)"])
    assert "Person(Alice)" in reasoner.facts
    assert "worksFor(Alice, Acme)" not in reasoner.facts
    assert not any("xsd:string" in r.conclusion for r in results)
    _, reasoner, _ = run(schema(), ["name(Alice, Alice Smith)"])
    assert "Person(Alice)" in reasoner.facts
    assert "Person(Alice Smith)" not in reasoner.facts


def test_equivalence_subproperty_inverse_transitive_and_symmetric():
    ontology = {
        "classes": [{"name": "Person", "equivalentClass": "Human"}, {"name": "Human"}],
        "properties": [
            {"name": "parentOf", "type": "object", "subPropertyOf": "ancestorOf", "inverseOf": "childOf"},
            {"name": "childOf", "type": "object"},
            {"name": "ancestorOf", "type": "object", "transitive": True},
            {"name": "knows", "type": "object", "symmetric": True},
        ],
    }
    _, reasoner, _ = run(ontology, ["Human(A)", "parentOf(A, B)", "childOf(C, B)", "knows(A, C)"])
    assert {"Person(A)", "parentOf(B, C)", "childOf(B, A)", "ancestorOf(A, C)", "knows(C, A)"} <= reasoner.facts


@pytest.mark.parametrize("field,value", [
    ("disjointWith", "Person"), ("restrictions", {"min": 1}),
    ("equivalentClass", {"intersectionOf": ["Person", "Organization"]}),
    ("parent", "Unknown"), ("equivalentClass", "owl:Thing"),
])
def test_unsupported_or_unresolved_axioms_never_silently_load(field, value):
    ontology = schema()
    ontology["classes"][0][field] = value
    reasoner = Reasoner()
    reasoner.add_rule("IF Existing(?x) THEN Kept(?x)")
    with pytest.raises(OntologyRuleCompilationError) as caught:
        OntologyRuleCompiler().load(ontology, reasoner)
    assert field in str(caught.value)
    assert len(reasoner.rules) == 1
    partial = OntologyRuleCompiler().compile(ontology, strict=False)
    assert partial.diagnostics


@pytest.mark.parametrize("change", [
    {"name": "Person"}, {"name": "Bad(?x)"},
    {"name": "Other", "uri": "https://example.org/hr#Employee"},
])
def test_name_and_iri_collisions_and_rule_injection_rejected(change):
    ontology = schema()
    ontology["classes"].append(change)
    with pytest.raises(OntologyRuleCompilationError):
        OntologyRuleCompiler().compile(ontology)


def test_cycles_and_repeat_loading_terminate_without_duplicate_rules():
    ontology = schema()
    ontology["classes"][1]["parent"] = "Employee"
    compiler, reasoner = OntologyRuleCompiler(), Reasoner()
    first = compiler.load(ontology, reasoner)
    second = compiler.load(ontology, reasoner)
    assert [r.rule_id for r in first.rules] == [r.rule_id for r in second.rules]
    assert len(reasoner.rules) == len(first.rules)
    assert reasoner.infer_facts(["Employee(Alice)"]) == ["Person(Alice)"]
    assert reasoner.forward_chain() == []


def test_datatype_constraints_and_boolean_flags_are_not_class_inferences():
    ontology = schema()
    ontology["properties"][1]["required"] = True
    ontology["properties"][1]["inverseOf"] = "worksFor"
    ontology["properties"][0]["transitive"] = "false"
    result = OntologyRuleCompiler().compile(ontology, strict=False)
    assert len(result.diagnostics) == 3
    assert not any("string(" in r.conclusion for r in result.rules)


@patch("semantica.ontology.llm_generator.create_provider")
def test_text_to_executable_inference_and_json_artifact(create):
    create.return_value.generate_structured.return_value = schema()
    engine = OntologyEngine()
    reasoner = Reasoner()
    ontology = engine.from_text("员工属于人，员工在机构工作。", reasoner=reasoner)
    assert ontology["rule_compilation"]["rules"]
    assert not ontology["rule_compilation"]["diagnostics"]
    assert set(reasoner.infer_facts(["worksFor(Alice, Acme)"])) == {
        "Employee(Alice)", "Person(Alice)", "Organization(Acme)"
    }
    json.dumps(ontology)
    # The loader recompiles schema; never trust cached/model-authored rules.
    ontology["rule_compilation"]["rules"] = [{"conclusion": "Injected(Alice)"}]
    fresh = engine.to_reasoner(ontology)
    assert "Injected(Alice)" not in fresh.infer_facts(["worksFor(Alice, Acme)"])
    assert len(fresh.rules) == len(reasoner.rules)


@patch("semantica.ontology.llm_generator.create_provider")
def test_llm_normalization_preserves_axioms_and_reports_unsupported(create):
    raw = schema()
    raw["classes"][0]["disjointWith"] = "Person"
    raw["properties"][0]["transitive"] = True
    raw["base_uri"] = "https://example.org/hr#"
    create.return_value.generate_structured.return_value = raw
    engine = OntologyEngine()
    with pytest.raises(OntologyRuleCompilationError, match="disjointWith"):
        engine.from_text("contradictory schema")
    ontology = engine.from_text("schema", strict=False)
    assert ontology["classes"][0]["disjointWith"] == "Person"
    assert ontology["properties"][0]["transitive"] is True
    assert ontology["rule_compilation"]["diagnostics"]
    assert ontology["classes"][1]["uri"] == "https://example.org/hr#Person"
    legacy = engine.from_text("schema", compile_rules=False)
    assert "rule_compilation" not in legacy
    with pytest.raises(ValueError):
        engine.from_text("schema", compile_rules=False, reasoner=Reasoner())


def test_imports_and_owl_characteristics_are_not_silently_ignored():
    ontology = schema()
    ontology["imports"] = ["https://example.org/imported"]
    ontology["properties"][0]["@type"] = "owl:FunctionalProperty"
    result = OntologyRuleCompiler().compile(ontology, strict=False)
    assert any("imports" in d for d in result.diagnostics)
    assert any("FunctionalProperty" in d for d in result.diagnostics)


@patch("semantica.ontology.llm_generator.create_provider")
def test_malformed_llm_collections_and_anonymous_parent_remain_visible(create):
    from semantica.utils.exceptions import ValidationError
    generator = LLMOntologyGenerator()
    with pytest.raises(ValidationError):
        generator._normalize_output({"classes": {}})
    ontology = generator._normalize_output({"classes": [{"name": "Broken", "parent": {}}]})
    with pytest.raises(OntologyRuleCompilationError):
        OntologyRuleCompiler().compile(ontology)
