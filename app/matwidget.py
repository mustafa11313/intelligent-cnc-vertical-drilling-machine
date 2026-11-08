from PyQt6.QtWidgets import *
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas
)
from matplotlib.figure import Figure


class MatWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas = FigureCanvas(Figure())

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.canvas.axes = self.canvas.figure.add_subplot(111)

        self.setLayout(layout)