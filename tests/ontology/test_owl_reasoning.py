"""Backend failures must never masquerade as successful OWL validation."""
import shutil
import subprocess
import sys

import pytest

from semantica.ontology.ontology_validator import OntologyValidator, validate_ontology

PREFIXES = '''@prefix : <https://example.org/test#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:ontology a owl:Ontology .
:A a owl:Class . :B a owl:Class ; owl:disjointWith :A .
'''


def ontology_file(tmp_path, axioms=""):
    path = tmp_path / "ontology.ttl"
    path.write_text(PREFIXES + axioms)
    return path


def test_missing_dependency_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "owlready2", None)
    result = OntologyValidator().validate(ontology_file(tmp_path))
    assert not result.valid
    assert result.consistent is None and result.satisfiable is None
    assert "semantica[owl]" in result.errors[0]


def test_structural_only_does_not_import_backend(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "owlready2", None)
    result = OntologyValidator(check_consistency=False, check_satisfiability=False).validate(
        ontology_file(tmp_path)
    )
    assert result.valid
    assert result.consistent is None and result.satisfiable is None


def test_bad_input_and_backend(tmp_path):
    result = OntologyValidator().validate(tmp_path / "missing.owl")
    assert not result.valid and result.consistent is None
    with pytest.raises(ValueError):
        OntologyValidator(reasoner="unknown")
    with pytest.raises(NotImplementedError):
        OntologyValidator().check_constraint("anything")


def test_failed_backend_and_auto_fallback(tmp_path, monkeypatch):
    owl = pytest.importorskip("owlready2")
    calls = []

    def fail(world, **kwargs):
        calls.append(world)
        raise RuntimeError("Java unavailable")

    monkeypatch.setattr(owl, "sync_reasoner", fail)
    result = OntologyValidator().validate(ontology_file(tmp_path))
    assert not result.valid and result.consistent is None
    assert "Java unavailable" in result.errors[0]
    monkeypatch.setattr(owl, "sync_reasoner_pellet", lambda world, **kw: calls.append(world))
    result = OntologyValidator(reasoner="auto").validate(ontology_file(tmp_path))
    assert result.valid and result.reasoner_used == "pellet"
    assert result.warnings and calls[-1] is not calls[-2]


def test_parent_alias_preserved_without_mutation():
    from rdflib import Graph, RDFS, URIRef
    schema = {"classes": [{"name": "Child", "uri": "https://example.org/Child",
                            "parent": "https://example.org/Parent"}], "properties": []}
    graph = Graph().parse(data=OntologyValidator()._rdf_payload(schema), format="xml")
    assert (URIRef("https://example.org/Child"), RDFS.subClassOf,
            URIRef("https://example.org/Parent")) in graph
    assert "subClassOf" not in schema["classes"][0]


@pytest.fixture
def java_backend():
    pytest.importorskip("owlready2")
    java = shutil.which("java")
    if not java or subprocess.run([java, "-version"], capture_output=True).returncode:
        pytest.skip("A working Java runtime is required")


@pytest.mark.integration
@pytest.mark.parametrize("backend", ["hermit", "pellet"])
@pytest.mark.parametrize("case", ["consistent", "unsatisfiable", "inconsistent"])
def test_real_reasoners(tmp_path, java_backend, backend, case):
    axioms = ""
    if case == "unsatisfiable":
        axioms = ":Impossible a owl:Class ; rdfs:subClassOf :A, :B ."
    elif case == "inconsistent":
        axioms = ":individual a :A, :B ."
    result = OntologyValidator(reasoner=backend).validate(ontology_file(tmp_path, axioms))
    assert result.reasoner_used == backend, result.errors
    if case == "consistent":
        assert result.valid and result.consistent and result.satisfiable
    elif case == "unsatisfiable":
        assert not result.valid and result.consistent and result.satisfiable is False
        assert result.unsatisfiable_classes == ["https://example.org/test#Impossible"]
    else:
        assert not result.valid and result.consistent is False
        assert result.satisfiable is None


@pytest.mark.integration
def test_wrapper_and_flags(tmp_path, java_backend):
    path = ontology_file(tmp_path)
    assert validate_ontology(path, method="pellet")["reasoner_used"] == "pellet"
    result = OntologyValidator(check_satisfiability=False).validate(path)
    assert result.consistent is True and result.satisfiable is None
    result = OntologyValidator(check_consistency=False).validate(path)
    assert result.consistent is None and result.satisfiable is True


def test_inconsistency_is_not_a_backend_failure(tmp_path, monkeypatch):
    owl = pytest.importorskip("owlready2")

    def inconsistent(*args, **kwargs):
        raise owl.OwlReadyInconsistentOntologyError()

    def unexpected(*args, **kwargs):
        pytest.fail("Logical inconsistency must not fall back to another reasoner")

    monkeypatch.setattr(owl, "sync_reasoner", inconsistent)
    monkeypatch.setattr(owl, "sync_reasoner_pellet", unexpected)
    result = OntologyValidator(reasoner="auto").validate(ontology_file(tmp_path))
    assert result.consistent is False and result.reasoner_used == "hermit"


@pytest.mark.integration
def test_repeated_calls_do_not_leak_axioms(tmp_path, java_backend):
    validator = OntologyValidator()
    result = validator.validate(ontology_file(tmp_path, ":individual a :A, :B ."))
    assert result.consistent is False
    result = validator.validate(ontology_file(tmp_path))
    assert result.consistent is True and result.satisfiable is True
