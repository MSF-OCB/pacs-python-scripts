class CaseInsensitiveDict(dict):
    def __init__(self, data=None):
        super().__init__()
        if data:
            for key, value in data.items():
                self[key] = value  # routes through __setitem__

    def __setitem__(self, key, value):
        super().__setitem__(key.upper(), value)

    def __getitem__(self, key):
        return super().__getitem__(key.upper())

    def get(self, key, default=None):
        return super().get(key.upper(), default)

    def __contains__(self, key):
        return super().__contains__(key.upper())


TEI_MSF_LOOKUP = CaseInsensitiveDict({
    "CLAVICLE": 300,
    "CSPINE": 300,
    "KNEE":300,
    "LEG":300,
    "SHOULDER":300,
    "SKULL":300,
    "ABDOMEN":400,
    "CHEST":400,
    "Chest*":400,
    "HIP":400,
    "LSPINE":400,
    "PELVIS":400,
    "TSPINE":400,
    "ARM":550,
    "ANKLE":550,
    "ELBOW":550,
    "FOOT":550,
    "HAND":550,
})