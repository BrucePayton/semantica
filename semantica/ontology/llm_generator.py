from typing import Any, Dict, List, Optional
from copy import deepcopy

from ..utils.exceptions import ProcessingError, ValidationError
from ..utils.logging import get_logger
from ..utils.progress_tracker import get_progress_tracker
from ..semantic_extract.providers import create_provider


class LLMOntologyGenerator:
    def __init__(self, provider: str = "openai", model: Optional[str] = None, **config):
        self.logger = get_logger("llm_ontology_generator")
        self.progress = get_progress_tracker()
        # Ensure progress tracker is enabled
        if not self.progress.enabled:
            self.progress.enabled = True
        self.provider_name = provider
        self.model = model
        self.config = config
        self.provider = create_provider(provider, model=model) if provider else None

    def set_provider(self, provider: str, model: Optional[str] = None, **kwargs):
        self.provider_name = provider
        self.model = model or self.model
        self.provider = create_provider(provider, model=self.model, **kwargs)

    def generate_ontology_from_text(self, text: str, **options) -> Dict[str, Any]:
        if not self.provider:
            raise ProcessingError("LLM provider not initialized")

        tracking_id = self.progress.start_tracking(
            module="ontology",
            submodule="LLMOntologyGenerator",
            message="Generating ontology from text",
        )

        base_uri = options.get("base_uri")
        name = options.get("name")
        version = options.get("version") or "1.0"

        prompt = self._build_prompt(text=text, name=name, base_uri=base_uri)

        try:
            result = self.provider.generate_structured(
                prompt, model=self.model or options.get("model"), temperature=options.get("temperature")
            )
        except Exception as e:
            self.progress.update_tracking(tracking_id, message="LLM generation failed")
            raise ProcessingError(f"LLM ontology generation failed: {e}")

        ontology = self._normalize_output(result, name=name, base_uri=base_uri, version=version)
        self.progress.update_tracking(tracking_id, message="Ontology generated")
        return ontology

    def _build_prompt(self, **kwargs) -> str:
        name = kwargs.get("name") or "GeneratedOntology"
        base_uri = kwargs.get("base_uri") or "https://example.org/ontology/"
        text = kwargs.get("text") or ""
        schema = """
{
  "name": "OntologyName",
  "base_uri": "https://example.org/ontology/",
  "classes": [
    {"name": "ClassName", "label": "Label", "comment": "Description", "parent": "ParentClass", "uri": "IRI"}
  ],
  "properties": [
    {"name": "propName", "type": "object|data", "domain": ["ClassName"], "range": ["ClassName|xsd:string"], "label": "Label", "comment": "Description", "uri": "IRI"}
  ]
}
"""
        instructions = (
            f"You are an ontology generator. Read the following text and produce a concise ontology in JSON. "
            f"Use '{base_uri}' for IRIs when missing. Only output valid JSON. "
            f"Prefer '{name}' as ontology name if appropriate. "
            "Declare every referenced class and property. Names must be unique identifiers "
            "(letters, digits, underscores; start with a letter). Use null for absent parent. "
            "Extract only axioms supported by the text; do not invent facts or rules. "
            "Optional named axioms: classes may include equivalentClass (name or list); "
            "properties may include subPropertyOf, inverseOf (name or list), "
            "transitive and symmetric (booleans). Parent may be a name or list. "
            "Keep constraints or complex class expressions explicitly in separate fields "
            "such as disjointWith or restrictions; never approximate them as inheritance. "
            "Do not output executable rule strings or code."
        )
        return f"{instructions}\n\nTEXT:\n{text}\n\nJSON SCHEMA EXAMPLE:\n{schema}"

    def _normalize_output(self, result: Dict[str, Any], **meta) -> Dict[str, Any]:
        if not isinstance(result, dict):
            raise ValidationError("Ontology response must be a JSON object")
        classes = result.get("classes", result.get("Classes", []))
        classes = [] if classes is None else classes
        properties = result.get("properties", result.get("Properties", []))
        properties = [] if properties is None else properties
        for collection in (classes, properties):
            if not isinstance(collection, list) or any(not isinstance(item, dict) for item in collection):
                raise ValidationError("Ontology classes and properties must be lists of objects")

        def ensure_uri(name: str, uri: Optional[str]) -> str:
            if uri:
                return uri
            base = meta.get("base_uri") or result.get("base_uri") or "https://example.org/ontology/"
            return f"{base}{name}"

        normalized_classes: List[Dict[str, Any]] = []
        for cls in classes:
            cname = cls.get("name") or cls.get("Name") or "Class"
            normalized_classes.append(
                {
                    **deepcopy({k: v for k, v in cls.items()
                                if k not in {"Name", "IRI", "Label", "Description", "Parent"}}),
                    "name": cname,
                    "uri": ensure_uri(cname, cls.get("uri") or cls.get("IRI")),
                    "label": cls.get("label") or cls.get("Label"),
                    "comment": cls.get("comment") or cls.get("Description"),
                    "parent": cls.get("parent", cls.get("Parent")),
                }
            )

        normalized_properties: List[Dict[str, Any]] = []
        for prop in properties:
            pname = prop.get("name") or prop.get("Name") or "property"
            dom = prop.get("domain", prop.get("Domain", []))
            rng = prop.get("range", prop.get("Range", []))
            ptype = prop.get("type", prop.get("Type", prop.get("@type", "object")))
            normalized_properties.append(
                {
                    **deepcopy({k: v for k, v in prop.items()
                                if k not in {"Name", "IRI", "Domain", "Range", "Type", "Label", "Description"}}),
                    "name": pname,
                    "type": ptype,
                    "domain": dom if isinstance(dom, list) else [] if dom is None else [dom],
                    "range": rng if isinstance(rng, list) else [] if rng is None else [rng],
                    "label": prop.get("label") or prop.get("Label"),
                    "comment": prop.get("comment") or prop.get("Description"),
                    "uri": ensure_uri(pname, prop.get("uri") or prop.get("IRI")),
                }
            )

        ontology: Dict[str, Any] = {
            **deepcopy({k: v for k, v in result.items() if k not in {"Classes", "Properties"}}),
            "uri": meta.get("base_uri") or result.get("base_uri"),
            "name": meta.get("name") or result.get("name"),
            "version": meta.get("version") or result.get("version") or "1.0",
            "classes": normalized_classes,
            "properties": normalized_properties,
            "metadata": {"source": "llm", "provider": self.provider_name},
        }

        if not ontology["uri"]:
            ontology["uri"] = meta.get("base_uri") or "https://example.org/ontology/"

        if not ontology["name"]:
            ontology["name"] = "GeneratedOntology"

        return ontology
