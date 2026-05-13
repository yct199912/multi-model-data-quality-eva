# services/model/src/core/state.py
from typing import Optional, Any

is_ready: bool = False
init_error: Optional[str] = None
provider: Optional[Any] = None