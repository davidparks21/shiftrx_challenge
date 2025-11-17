from typing import List
from dataclasses import dataclass, asdict


@dataclass
class AgentConversation:
    def __init__(self, discussion_history: List[str] = None):
        pass

    discussion_history: List[str] = None

@dataclass
class AgentQuery(AgentConversation):
    def __init__(self, user_prompt: str, discussion_history: List[str] = None):
        super().__init__(discussion_history)
        self.user_prompt = user_prompt

    query: str = None

@dataclass
class AgentResponse(AgentConversation):
    def __init__(self, response: str, approval_required: bool = False, discussion_history: List[str] = None):
        super().__init__(discussion_history)
        self.response = response
        self.approval_required = approval_required

    response: str = None
    approval_required: bool = None

