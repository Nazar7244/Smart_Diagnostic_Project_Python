from PySide6.QtCore import QObject, Signal

from desktop_visuals import label

from ..auth import require
from ..models import Session
from ..permissions import Perm
from ..services import Services


class AppContext(QObject):
    """State shared by every page of one signed-in window: services, the current user and change signals."""

    history_changed = Signal()
    equipment_changed = Signal()
    users_changed = Signal()
    user_updated = Signal()

    def __init__(self, services: Services, session: Session):
        super().__init__()
        self.services = services
        self.user = session.user
        self.token = session.token
        self.session = session
        self.technical_labels = []
        self.bilingual = True

    def can(self, perm: Perm) -> bool:
        return self.user.can(perm)

    def require(self, perm: Perm):
        require(self.user, perm)

    # Secondary (English) captions that the original "language" preference can hide.
    def technical(self, text, role="technical"):
        widget = label(text, role)
        widget.setVisible(self.bilingual)
        self.technical_labels.append(widget)
        return widget

    def set_bilingual(self, enabled: bool):
        self.bilingual = enabled
        for widget in self.technical_labels:
            widget.setVisible(enabled)

    def update_user(self, user):
        self.user = user
        self.user_updated.emit()
