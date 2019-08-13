import re
import logging


def re_list_compile(re_list):
    return [(re.compile(expr), repl) for expr, repl in re_list]

def chunks(list_, size):
    for i in range(0, len(list_), size):
        yield list_[i:i + size]

def configure_logger(name,
                     log_file=None,
                     log_format=None,
                     log_level=logging.INFO):
    if isinstance(log_file, str):
        handler = logging.FileHandler(log_file, 'a')
    else:
        handler = logging.StreamHandler(log_file)

    formatter = logging.Formatter(log_format)
    logger = logging.getLogger(name)

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(log_level)

    return logger
