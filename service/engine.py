"""Persona engine: seller id -> persona spec -> Sarvam agent route + variables. Holds features in memory."""
import threading

import pandas as pd

from persona.generator import generate, load_manual_overrides
from persona.playbook import load_library
from persona.seller_features import load_features
from sarvam_agent.to_variables import variables
from sarvam_agent.variants import VARIANTS
from service import settings


class PersonaEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self.reload()

    def reload(self):
        """(Re)load seller features, the playbook and manual overrides; called at start and after the nightly job."""
        feats = load_features()
        with self._lock:
            self.features = feats.set_index("fk_glusr_usr_id", drop=False)
            self.library = load_library()
            self.overrides = load_manual_overrides()

    def has(self, seller_id: int) -> bool:
        return seller_id in self.features.index

    def spec(self, seller_id: int) -> dict:
        row = self.features.loc[seller_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return generate(row.to_dict(), self.library, self.overrides)

    def route(self, seller_id: int, spec: dict | None = None) -> dict:
        spec = spec or self.spec(seller_id)
        variant, vars_ = variables(spec)
        agent = settings.AGENTS[variant]
        return {
            "seller_id": seller_id,
            "persona_label": spec["persona_label"],
            "variant": variant,
            "agent_name": agent["name"],
            "app_id": agent["app_id"],
            "app_version": agent["committed_version"],
            "initial_language": VARIANTS[variant]["initial_language"],
            "do_not_call": spec["conversation_plan"]["opening_style"]["value"] == "compliance_only",
            "variables": vars_,
            "overall_confidence": spec["overall_confidence"],
            "manual_overrides": spec["manual_overrides"],
        }


_engine: PersonaEngine | None = None


def engine() -> PersonaEngine:
    global _engine
    if _engine is None:
        _engine = PersonaEngine()
    return _engine
