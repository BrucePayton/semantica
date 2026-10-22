---
title: "Ontology Module"
description: "Automated ontology generation, SHACL validation, OWL/RDF export, namespace management, and LLM-powered ontology generation."
icon: "sitemap"
---

`semantica.ontology` provides the full lifecycle for knowledge graph schemas:

- Auto-generate ontologies from KG data via a 5-stage pipeline (Semantic Network → YAML → Types → Hierarchy → TTL)
- LLM-powered ontology generation for complex domains via `LLMOntologyGenerator`
- SHACL validation: generate shapes, validate graphs, and get violation reports
- OWL/RDF export in Turtle, RDF/XML, and JSON-LD formats
- Ontology Hub visual editor available in `semantica.explorer` (v0.5.0)


## Exported Classes

| Class | Role |
| :--- | :--- |
| `OntologyEngine` | Unified facade orchestrating the full ontology lifecycle |
| `OntologyGenerator` | Auto-generate ontologies from KG data (5-stage pipeline) |
| `LLMOntologyGenerator` | LLM-powered ontology generation for complex domains |
| `SHACLGenerator` | Generate SHACL shapes from an ontology or KG schema |
| `OntologyValidator` | Validate any graph against SHACL shapes: returns `SHACLValidationReport` |
| `OntologyQualityGate` | Run deterministic ontology/KG quality checks for CI |
| `OWLGenerator` | Serialize ontologies to Turtle, RDF/XML, JSON-LD |
| `NamespaceManager` | IRI generation, prefix management, and namespace binding |
| `OntologyEvaluator` | Coverage, completeness, and granularity quality metrics |
| `ClassInferrer` | Infer classes from entity type patterns |
| `PropertyGenerator` | Generate properties from entity attributes and relationships |
| `AssociativeClassBuilder` | Model N-ary relationships as intermediate OWL classes |


## Getting Started

**`OntologyEngine`** is your main entry point for the complete ontology workflow:

```python
from semantica.ontology import OntologyEngine

# Initialize with base URI for your domain
engine = OntologyEngine(base_uri="https://example.org/ontology/")

# Generate ontology from your knowledge graph data
ontology = engine.from_data({"entities": entities, "relationships": relationships})

# Validate a graph against the generated SHACL shapes
report = engine.validate_graph(kg, ontology=ontology)
if not report.conforms:
    for v in report.violations:
        print(f"{v.severity}: {v.message} on {v.focus_node}")

# Export to OWL Turtle
engine.export_owl(ontology, "ontology.ttl", format="turtle")
```

## OntologyEngine (Unified Facade)

**`OntologyEngine`** orchestrates the full ontology lifecycle: **generation, validation, export, and evaluation**:

```python
from semantica.ontology import OntologyEngine

engine = OntologyEngine(base_uri="https://example.org/ontology/")

# Generate ontology from KG data
ontology = engine.from_data({"entities": entities, "relationships": relationships})

# Validate a graph against the generated SHACL shapes
report = engine.validate_graph(kg, ontology=ontology)
if not report.conforms:
    for v in report.violations:
        print(f"{v.severity}: {v.message} on {v.focus_node}")

# Export to OWL Turtle
engine.export_owl(ontology, "ontology.ttl", format="turtle")
```

### OntologyEngine Methods

| Method | Description |
| :------ | :----------- |
| `from_data(data)` | Run the 5-stage pipeline on entity/relationship data |
| `validate_graph(kg, ontology=...)` | Check a knowledge graph against generated SHACL shapes |
| `quality_check(ontology, graph_data=...)` | Return a deterministic quality report and CI-friendly pass/fail result |
| `export_owl(ontology, path, format)` | Serialize to `"turtle"`, `"xml"`, or `"json-ld"` |
| `evaluate(ontology, kg)` | Compute coverage, completeness, and granularity metrics |

### Ontology Quality Gate

Use the quality gate before export or deployment to catch structural issues
without adding a runtime dependency:

```python
from semantica.ontology import ontology_quality_check

report = ontology_quality_check(
    ontology,
    graph_data=kg,
    thresholds={"min_coverage": 0.8},
)

if not report.passed:
    for issue in report.issues:
        print(issue.code, issue.message)
```

The report checks class/property coverage, orphan schema elements, domain and
range references, and unresolved KG relationship endpoints. It includes
machine-readable issue codes, severity, counts, metrics, and threshold
failures. The first version reports findings only; it does not auto-fix data.

### Thresholds

`min_coverage` (default `0.0`) sets the minimum required `coverage` score, the average of class and property coverage from `0.0` to `1.0`; the gate fails below it. `max_errors` (default `0.0`) caps how many `error`/`critical` issues are allowed before the gate fails. `max_warnings` (default `None`) caps `warning` issues the same way, and `None` means warnings alone never fail the gate. `fail_on_warnings` is a separate parameter, not a `thresholds` key, passed to `OntologyQualityGate(...)` or `.check(...)` directly; when `True`, a single warning fails the gate regardless of `max_warnings`.

## OntologyGenerator (5-Stage Pipeline)

**`OntologyGenerator`** auto-generates a formal ontology from your knowledge graph entities and relationships:

```python
from semantica.ontology import OntologyGenerator

generator = OntologyGenerator(base_uri="https://example.org/ontology/")
ontology  = generator.generate_ontology({
    "entities":      entities,
    "relationships": relationships,
})
```

<Steps>
  <Step title="Semantic Network Parsing">
    Extract concepts and patterns from entity types and relationship structures in the source data.
  </Step>
  <Step title="YAML-to-Definition">
    Transform the extracted patterns into intermediate class and property definitions.
  </Step>
  <Step title="Definition-to-Types">
    Map definitions to OWL constructs: `owl:Class`, `owl:ObjectProperty`, `owl:DatatypeProperty`.
  </Step>
  <Step title="Hierarchy Generation">
    Build taxonomy trees using transitive closure and cycle detection: produces `rdfs:subClassOf` chains.
  </Step>
  <Step title="TTL Generation">
    Serialize the final ontology to Turtle format using `rdflib`. Also available: RDF/XML and JSON-LD.
  </Step>
</Steps>

## SHACL Validation

Generate SHACL shapes from an ontology and validate any graph against them:

```python
from semantica.ontology import SHACLGenerator, OntologyValidator, SHACLValidationReport, SHACLViolation

# Generate shapes from ontology
generator  = SHACLGenerator()
shapes     = generator.generate(ontology)
shapes_ttl = shapes.serialize(format="turtle")

# Validate a graph against the shapes
validator = OntologyValidator()
report: SHACLValidationReport = validator.validate_graph(kg, ontology=ontology)

if not report.conforms:
    violation: SHACLViolation
    for violation in report.violations:
        print(f"{violation.severity}: {violation.message}")
        print(f"  Node: {violation.focus_node}")
        print(f"  Path: {violation.result_path}")
```

### Validation Report Fields

| Field | Type | Description |
| :----- | :---- | :----------- |
| `conforms` | `bool` | `True` if the graph passes all SHACL constraints |
| `violations` | `List[SHACLViolation]` | Detailed failure records |
| `focus_node` | `str` | IRI of the violating graph node |
| `result_path` | `str` | IRI of the violating property path |
| `severity` | `str` | `"Violation"`, `"Warning"`, or `"Info"` |
| `message` | `str` | Human-readable constraint failure description |

## LLM-Powered Ontology Generation

For complex or novel domains where schema patterns are hard to infer statistically:

```python
from semantica.ontology import LLMOntologyGenerator

# Initialize with your preferred LLM provider
generator = LLMOntologyGenerator(provider="openai")  # or "anthropic", "groq", etc.
ontology  = generator.generate_ontology_from_text(
    text="A biomedical ontology for clinical trial protocols involving patients, trials, interventions, and outcomes."
)
```

## OWL / RDF Export

```python
from semantica.ontology import OWLGenerator

generator = OWLGenerator()
generator.export_owl(ontology, path="ontology.ttl",  format="turtle")
generator.export_owl(ontology, path="ontology.owl",  format="xml")
generator.export_owl(ontology, path="ontology.json", format="json-ld")
```

## Namespace Management

```python
from semantica.ontology import NamespaceManager

ns = NamespaceManager(base_uri="https://example.org/")
ns.register("ex",     "https://example.org/")
ns.register("schema", "https://schema.org/")
ns.register("owl",    "http://www.w3.org/2002/07/owl#")

# Generate IRIs for classes and properties
class_iri    = ns.generate_class_iri("Person")
property_iri = ns.generate_property_iri("worksFor")
```

## Ontology Evaluation

Measure coverage, completeness, and granularity of a generated ontology:

```python
from semantica.ontology import OntologyEvaluator

evaluator = OntologyEvaluator()
result    = evaluator.evaluate_ontology(ontology, kg)

print(f"Class coverage:    {result.class_coverage:.2f}")
print(f"Property coverage: {result.property_coverage:.2f}")
print(f"Completeness:      {result.completeness:.2f}")
print(f"Granularity:       {result.granularity:.2f}")

for gap in result.gaps:
    print(f"Gap: {gap.description}")
```

## Common Workflows

<Tabs>
  <Tab title="Quick Start">
    **Generate and validate an ontology in 3 steps:**

    ```python
    from semantica.ontology import OntologyEngine

    # 1. Initialize engine
    engine = OntologyEngine(base_uri="https://yourcompany.com/ontology/")

    # 2. Generate from your data
    ontology = engine.from_data({"entities": entities, "relationships": relationships})

    # 3. Validate against a knowledge graph
    report = engine.validate_graph(kg, ontology=ontology)
    if report.conforms:
        print("✓ Graph conforms to ontology")
    else:
        print(f"✗ Found {len(report.violations)} violations")
    ```
  </Tab>
  <Tab title="LLM-Powered Generation">
    **Generate ontologies from text descriptions:**

    ```python
    from semantica.ontology import LLMOntologyGenerator

    generator = LLMOntologyGenerator(provider="openai")
    ontology = generator.generate_ontology_from_text("""
        Create an e-commerce ontology with products, customers, orders, 
        categories, reviews, and payment methods.
    """)

    # Refine with additional constraints
    engine = OntologyEngine()
    validated = engine.validate(ontology)
    ```
  </Tab>
  <Tab title="Export and Integration">
    **Export ontologies in multiple formats:**

    ```python
    from semantica.ontology import OntologyEngine

    engine = OntologyEngine()

    # Export as OWL/Turtle for Protégé
    engine.export_owl(ontology, "schema.ttl", format="turtle")

    # Export as JSON-LD for web applications
    engine.export_owl(ontology, "schema.jsonld", format="json-ld")

    # Generate SHACL shapes for validation
    engine.export_shacl(ontology, "shapes.ttl")
    ```
  </Tab>
</Tabs>

## Ingest an Existing Ontology

Load and parse an ontology file for downstream use:

```python
from semantica.ontology import ingest_ontology

ontology_data = ingest_ontology("schema.ttl")     # Turtle
ontology_data = ingest_ontology("schema.owl")     # OWL/XML
ontology_data = ingest_ontology("schema.jsonld")  # JSON-LD
```

<Note>
  Ontology versioning (`VersionManager`, `OntologyVersion`) has moved to `semantica.change_management`. Import from there: `from semantica.change_management import VersionManager`.
</Note>

- [Reasoning](/reference/reasoning) — Apply inference rules over ontology axioms.
- [Knowledge Graph](/reference/kg) — The graph being modeled by the ontology.
- [Export](/reference/export) — Export ontologies as RDF, OWL, or JSON-LD.
- [Conflicts](/reference/conflicts) — Detect ontology constraint violations.

## OWL consistency and class satisfiability

Install the optional backend and put a working Java runtime on `PATH` (tested
with Java 17 and Owlready2 0.49; the extra pins this compatible version):

```bash
pip install 'semantica[owl]'
java -version
```

```python
from semantica.ontology.ontology_validator import OntologyValidator

result = OntologyValidator(reasoner="hermit").validate("ontology.ttl")
# reasoner="pellet" selects Pellet; "auto" tries HermiT, then Pellet on
# execution failure. A logical inconsistency does not trigger fallback.
print(result.valid, result.consistent, result.satisfiable)
print(result.unsatisfiable_classes, result.errors)
```

The validator loads each input into an isolated Owlready2 World, performs real
classification, and closes the World afterward. Files are parsed with RDFLib
and converted to RDF/XML. Use `input_format="turtle"` for files without a
recognizable extension. Imported ontologies are loaded by Owlready2 and must be
resolvable; load or backend failures are reported in `errors`.

- `consistent=True` means the whole ontology has a model.
- `satisfiable=True` means every named class, excluding `owl:Nothing`, is
  satisfiable. A consistent ontology can still contain an empty, unsatisfiable
  class; its IRI is returned in `unsatisfiable_classes` and `valid` is false.
- `None` means a check was disabled or its result is unknown. Missing dependencies,
  Java failures, and parse errors set `valid=False`; they never imply consistency.
- A globally inconsistent ontology sets `consistent=False`; class satisfiability
  remains unknown because classification did not complete.

Schema dictionaries are also accepted through the existing OWL exporter (including
normalization of `parent` to `subClassOf`). They support only the axioms that exporter
can express. To validate restrictions, disjointness, individuals, and other complex
OWL axioms, supply an OWL/RDF file; these are not inferred from arbitrary dictionary
keys. Validation does not modify the source schema or save inferred triples.

Both checks are enabled by default, including when the validator is used by
`OntologyEngine` or the ontology quality gate. For structural/syntax checking
without Java or Owlready2, explicitly use:

```python
validator = OntologyValidator(check_consistency=False, check_satisfiability=False)
```

`check_constraint()` does not evaluate arbitrary strings and raises
`NotImplementedError`. Use `OntologyEngine.validate_graph()` for SHACL constraints.
The `validate_ontology(..., method="hermit" | "pellet" | "auto")` convenience
function honors backend selection and returns the same result fields as a dictionary.

Backend semantics follow the [Owlready2 reasoning documentation](https://owlready2.readthedocs.io/en/v0.49/reasoning.html).

## Compile text-generated ontologies into inference rules

`OntologyEngine.from_text()` now automatically compiles the generated schema into
positive Horn rules. The returned dictionary includes a JSON-compatible
`rule_compilation` artifact with `rules`, `symbols`, and `diagnostics`. This step
is deterministic; only the preceding text extraction calls an LLM.

```python
from semantica.ontology import OntologyEngine
from semantica.reasoning import Reasoner

engine = OntologyEngine(provider="openai", model="YOUR_MODEL")
reasoner = Reasoner()
ontology = engine.from_text(
    "Employee is a subclass of Person. worksFor is an object property "
    "with domain Employee and range Organization. "
    "Use exactly these class and property names.",
    reasoner=reasoner,
)

# Inspect the generated predicates and axioms before supplying your facts.
print(ontology["rule_compilation"])
results = reasoner.infer_with_results(["worksFor(Alice, Acme)"])
for result in results:
    print(result.conclusion, result.premises, result.rule_used.metadata)
# Given the specified schema: Employee(Alice), Person(Alice), Organization(Acme).
```

Alternatively, call `engine.to_reasoner(ontology)` to compile and load a fresh
reasoner, or `engine.compile_rules(ontology)` to get `RuleCompilationResult`
without loading anything. `OntologyRuleCompiler` is also exported for use without
constructing an engine or LLM provider. `to_reasoner()` always recompiles the
current schema; it never executes a cached/model-authored `rule_compilation` field.

| Schema axiom | Generated implication |
| --- | --- |
| `Employee.parent = Person` (also `subClassOf`, `subclassOf`) | `Employee(?x) → Person(?x)` |
| `Person.equivalentClass = Human` | Both class inclusion directions |
| `worksFor.domain = Employee` | `worksFor(?x, ?y) → Employee(?x)` |
| Object property `worksFor.range = Organization` | `worksFor(?x, ?y) → Organization(?y)` |
| `p.subPropertyOf = q` | `p(?x, ?y) → q(?x, ?y)` |
| Object property `p.inverseOf = q` | Both reversed-argument implications |
| Object property `p.transitive = true` | `p(?x, ?y) AND p(?y, ?z) → p(?x, ?z)` |
| Object property `p.symmetric = true` | `p(?x, ?y) → p(?y, ?x)` |

Named references accept declared names or full declared IRIs. Predicate names
must be unique identifiers across classes and properties; ambiguity is rejected
instead of merging different terms. Multiple parents/domains/ranges produce one
rule per named class (intersection semantics). Domain/range axioms infer types
from an existing relation; they do **not** require or invent relation instances.
Datatype ranges do not produce class facts. `owl:Thing` superclass/domain/range
bounds are tautological and omitted; equivalence to `owl:Thing` is unsupported.

Facts use the existing reasoner's predicate notation and spacing:
`Employee(Alice)` and `worksFor(Alice, Acme)`. Use the predicate names shown in the
artifact's symbol table; input IRI aliases are resolved in the schema, not in fact
strings. This interface does not automatically ingest RDF triples or KG dictionaries.
Rules carry deterministic IDs and source-axiom metadata; inference results retain
matched premises. Repeated loading is idempotent under the existing rule deduplication.

Strict compilation is the default. Unsupported fields (for example `disjointWith`,
cardinality/required constraints, anonymous restrictions, or property chains),
unresolved references, invalid names, and unresolved imports raise
`OntologyRuleCompilationError` **before** any rules are loaded. The exception's
`result` contains diagnostics and the reviewable supported subset. Model output
normalization preserves these fields so they cannot disappear before compilation.
Use `strict=False` only when you deliberately want that subset, and inspect
`rule_compilation["diagnostics"]`. `compile_rules=False` restores schema-only
`from_text()` behavior and cannot be combined with a target reasoner.

This compiler implements the listed named positive fragment, not complete OWL DL
reasoning or SHACL validation. Use the OWL validator for satisfiability/consistency
and SHACL for data constraints. LLM extraction quality still determines whether the
input axioms express the intended text; compilation is not a proof of that fidelity.
