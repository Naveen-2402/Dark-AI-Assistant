import uuid
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class ChatSession:
    id: str
    title: str
    role: str                  # the "system" role text the user provides
    messages: List[Dict] = field(default_factory=list)  # OpenAI-style messages

    def system_message(self):
        return {"role": "system", "content": self.role}

    def messages_for_model(self, max_pairs: int = 40) -> List[Dict]:
        """
        Returns system + the last `max_pairs` (user/assistant) messages.
        """
        non_system = [m for m in self.messages if m["role"] in ("user", "assistant")]
        trimmed = non_system[-(max_pairs*2):]  # roughly pairs
        return [self.system_message()] + trimmed

def new_chat(role_text: str) -> ChatSession:
    chat_id = str(uuid.uuid4())[:8]
    title = role_text.strip()[:40] or "New Chat"
    return ChatSession(id=chat_id, title=title, role=role_text.strip(), messages=[])
