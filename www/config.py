import config_default


class Dict(dict):
    def __init__(self, names=(), values=(), **kw):
        super(Dict, self).__init__(**kw)
        for k, v in zip(names, values):
            self[k] = v

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Dict' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value


def merge(defaults, ovveride):
    ret = dict()
    for k, v in defaults.items():
        if k in ovveride:
            if isinstance(v, dict):
                ret[k] = merge(v, ovveride[k])
            else:
                ret[k] = ovveride[k]
        else:
            ret[k] = v
    return ret


def to_dict(d):
    ret = Dict()
    for k, v in d.items():
        ret[k] = to_dict(v) if isinstance(v, dict) else v
    return ret


configs = config_default.configs
try:
    import config_override
    configs = merge(configs, config_override.configs)
except ImportError:
    pass

configs = to_dict(configs)
print(configs)
