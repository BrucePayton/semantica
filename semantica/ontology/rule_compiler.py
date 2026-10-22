"""Compile a named, positive ontology fragment into executable Horn rules.

This is not an OWL DL reasoner. Constraints and anonymous class expressions are
reported rather than approximated. No model output is executed as Python/code.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from typing import Any, Dict, List

from ..reasoning.reasoner import Reasoner, Rule


@dataclass
class RuleCompilationResult:
    rules: List[Rule] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)
    symbols: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable review artifact, not a rule loading format."""
        return {
            "rules": [
                {"rule_id": r.rule_id, "conditions": list(r.conditions),
                 "conclusion": r.conclusion, "metadata": deepcopy(r.metadata)}
                for r in self.rules
            ],
            "diagnostics": list(self.diagnostics),
            "symbols": dict(self.symbols),
        }


class OntologyRuleCompilationError(ValueError):
    def __init__(self, result: RuleCompilationResult):
        self.result = result
        super().__init__("Ontology rule compilation failed: " + "; ".join(result.diagnostics))


class OntologyRuleCompiler:
    """Translate named axioms, using declared names as predicate symbols.

    References may use a declared name or its full IRI. Names must be unique
    identifiers across classes and properties. Strict mode rejects any unsupported
    semantic field; non-strict mode returns supported rules with diagnostics.
    """
    _annotations = {"name", "uri", "label", "comment", "description", "metadata", "@type"}
    _class_fields = _annotations | {
        "parent", "subClassOf", "subclassOf", "equivalentClass", "properties", "entity_count"
    }
    _property_fields = _annotations | {
        "type", "domain", "range", "subPropertyOf", "inverseOf", "transitive", "symmetric"
    }
    _top_fields = {
        "name", "uri", "base_uri", "version", "classes", "properties", "metadata",
        "namespace", "description", "rule_compilation", "imports",
    }
    _thing = {"owl:Thing", "http://www.w3.org/2002/07/owl#Thing"}

    def compile(self, ontology: Dict[str, Any], *, strict: bool = True) -> RuleCompilationResult:
        result = RuleCompilationResult()
        if not isinstance(ontology, dict):
            raise TypeError("ontology must be a dictionary")
        declarations = {}
        aliases = {}
        bad_aliases = set()
        seen_rules = {}

        def warn(message):
            if message not in result.diagnostics:
                result.diagnostics.append(message)

        def unknown_fields(value, allowed, location):
            for key in sorted(set(value) - allowed):
                warn(f"{location}.{key}: unsupported field; not compiled")

        unknown_fields(ontology, self._top_fields, "ontology")
        if ontology.get("imports"):
            warn("ontology.imports: imported axioms must be resolved and merged before compilation")
        for collection, kind in (("classes", "class"), ("properties", "property")):
            entries = ontology.get(collection, [])
            if not isinstance(entries, list):
                warn(f"{collection}: expected a list")
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    warn(f"{collection}: each declaration must be a dictionary")
                    continue
                name = entry.get("name")
                if not isinstance(name, str) or not re.fullmatch(r"[^\W\d]\w*", name):
                    warn(f"{collection}: invalid predicate name {name!r}")
                    continue
                if name in declarations:
                    warn(f"{name}: duplicate predicate name")
                    bad_aliases.add(name)
                    continue
                declarations[name] = (kind, entry)
                if entry.get("uri") in ("http://www.w3.org/2002/07/owl#Thing", "http://www.w3.org/2002/07/owl#Nothing"):
                    warn(f"{name}: built-in OWL classes cannot be redefined as ordinary predicates")
                    bad_aliases.add(name)
                rdf_type = entry.get("@type")
                allowed_types = ({"owl:Class", "Class"} if kind == "class" else
                                 {"owl:ObjectProperty", "ObjectProperty", "owl:DatatypeProperty", "DatatypeProperty"})
                if rdf_type is not None and (not isinstance(rdf_type, str) or rdf_type not in allowed_types):
                    warn(f"{name}.@type: unsupported declaration type {rdf_type!r}")
                unknown_fields(entry, self._class_fields if kind == "class" else self._property_fields, name)
                for alias in (name, entry.get("uri")):
                    if alias is None:
                        continue
                    if not isinstance(alias, str) or not alias:
                        warn(f"{name}: invalid IRI")
                        continue
                    if alias in aliases and aliases[alias] != name:
                        warn(f"{alias}: ambiguous name/IRI reference")
                        bad_aliases.add(alias)
                    aliases[alias] = name
        result.symbols = {a: n for a, n in aliases.items() if a not in bad_aliases}

        def refs(value):
            return value if isinstance(value, list) else [] if value is None else [value]

        def resolve(value, kind, location):
            if isinstance(value, str) and kind == "class" and value in self._thing:
                return None  # No useful classification follows from a Thing bound.
            if not isinstance(value, str) or value not in result.symbols:
                warn(f"{location}: unresolved or non-named reference {value!r}")
                return None
            name = result.symbols[value]
            if declarations[name][0] != kind or name in bad_aliases:
                warn(f"{location}: expected an unambiguous {kind}: {value!r}")
                return None
            return name

        def emit(conditions, conclusion, owner, axiom, target):
            key = (tuple(conditions), conclusion)
            source = {"entity": owner, "axiom": axiom, "target": target}
            if key in seen_rules:
                if source not in seen_rules[key].metadata["axioms"]:
                    seen_rules[key].metadata["axioms"].append(source)
                return
            digest = sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:20]
            rule = Rule(
                rule_id=f"ontology_{digest}", name=f"{owner}: {axiom}",
                conditions=conditions, conclusion=conclusion,
                metadata={"source": "ontology_compiler", "ontology": ontology.get("uri"),
                          "axioms": [source]},
            )
            seen_rules[key] = rule
            result.rules.append(rule)

        def prop_kind(entry):
            value = entry.get("type", entry.get("@type", "object"))
            if value in ("object", "ObjectProperty", "owl:ObjectProperty"):
                return "object"
            if value in ("data", "datatype", "DatatypeProperty", "owl:DatatypeProperty"):
                return "data"
            return None

        for name, (kind, entry) in declarations.items():
            if name in bad_aliases:
                continue
            if kind == "class":
                for field_name in ("parent", "subClassOf", "subclassOf", "equivalentClass"):
                    for ref in refs(entry.get(field_name)):
                        if field_name == "equivalentClass" and isinstance(ref, str) and ref in self._thing:
                            warn(f"{name}.{field_name}: equivalence to owl:Thing is unsupported")
                            continue
                        target = resolve(ref, "class", f"{name}.{field_name}")
                        if target is None:
                            continue
                        emit([f"{name}(?x)"], f"{target}(?x)", name, field_name, ref)
                        if field_name == "equivalentClass":
                            emit([f"{target}(?x)"], f"{name}(?x)", name, field_name, ref)
                continue
            pkind = prop_kind(entry)
            if pkind is None:
                warn(f"{name}.type: unsupported property type {entry.get('type')!r}")
                continue
            declared_type = entry.get("@type")
            if (declared_type in ("owl:DatatypeProperty", "DatatypeProperty") and pkind != "data"
                    or declared_type in ("owl:ObjectProperty", "ObjectProperty") and pkind != "object"):
                warn(f"{name}: type and @type disagree")
                continue
            atom = f"{name}(?x, ?y)"
            for field_name, variable in (("domain", "?x"), ("range", "?y")):
                if field_name == "range" and pkind == "data":
                    # Datatype membership is a validation concern, not a class fact.
                    if any(not isinstance(ref, str) for ref in refs(entry.get("range"))):
                        warn(f"{name}.range: anonymous datatype expressions are unsupported")
                    continue
                for ref in refs(entry.get(field_name)):
                    target = resolve(ref, "class", f"{name}.{field_name}")
                    if target is not None:
                        emit([atom], f"{target}({variable})", name, field_name, ref)
            for field_name in ("subPropertyOf", "inverseOf"):
                for ref in refs(entry.get(field_name)):
                    target = resolve(ref, "property", f"{name}.{field_name}")
                    if target is None:
                        continue
                    target_kind = prop_kind(declarations[target][1])
                    if pkind != target_kind or (field_name == "inverseOf" and pkind != "object"):
                        warn(f"{name}.{field_name}: incompatible property kinds")
                        continue
                    if field_name == "subPropertyOf":
                        emit([atom], f"{target}(?x, ?y)", name, field_name, ref)
                    else:
                        emit([atom], f"{target}(?y, ?x)", name, field_name, ref)
                        emit([f"{target}(?x, ?y)"], f"{name}(?y, ?x)", name, field_name, ref)
            for field_name in ("transitive", "symmetric"):
                flag = entry.get(field_name, False)
                if not isinstance(flag, bool):
                    warn(f"{name}.{field_name}: expected a boolean")
                elif flag:
                    if pkind != "object":
                        warn(f"{name}.{field_name}: only object properties are supported")
                    elif field_name == "transitive":
                        emit([atom, f"{name}(?y, ?z)"], f"{name}(?x, ?z)", name, field_name, True)
                    else:
                        emit([atom], f"{name}(?y, ?x)", name, field_name, True)
        if strict and result.diagnostics:
            raise OntologyRuleCompilationError(result)
        return result

    def load(self, ontology: Dict[str, Any], reasoner: Reasoner, *, strict: bool = True) -> RuleCompilationResult:
        """Compile before loading so a strict failure leaves the reasoner untouched."""
        result = self.compile(ontology, strict=strict)
        for rule in result.rules:
            reasoner.add_rule(rule)
        return result
