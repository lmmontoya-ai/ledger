"""ledger.runtime — the impure layer: providers, episodes, logs, replay.

Everything below this package is pure (environment §12); everything that
touches a network or a clock lives here.  The runtime follows environment
§8.3 for bad output and provider failure, and plan §3.8 for routing,
provider identity, and trace registration.
"""
from .agents import ModelAgent, ScriptedAgent, parse_reply
from .config import ModelSpec, load_models
from .episode import run_episode
from .log import EpisodeLogger, read_records
from .openrouter import (BudgetExceeded, CallResult, CostMeter,
                         EpisodeAbandoned, OpenRouterClient, ProviderError)
from .replay import PolicyBatch, load_events, sample_policy, state_at
from .tools import action_from_tool_call, load_tools

__all__ = [
    "ModelAgent", "ScriptedAgent", "parse_reply",
    "ModelSpec", "load_models",
    "run_episode",
    "EpisodeLogger", "read_records",
    "BudgetExceeded", "CallResult", "CostMeter", "EpisodeAbandoned",
    "OpenRouterClient", "ProviderError",
    "PolicyBatch", "load_events", "sample_policy", "state_at",
    "action_from_tool_call", "load_tools",
]
