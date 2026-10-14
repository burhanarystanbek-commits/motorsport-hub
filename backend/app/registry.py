from .adapters.jolpica_f1 import JolpicaF1


def get_adapters():
    # Add new series here once their adapter is written AND tested.
    return [JolpicaF1()]
