from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        title = QLabel("Esasy panel")
        title.setObjectName("pageTitle")
        description = QLabel(
            "Bu ýerde girdeji, peýda, satyşlar we sklad galyndylary görkeziler."
        )
        description.setWordWrap(True)
        description.setObjectName("mutedText")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addStretch()
