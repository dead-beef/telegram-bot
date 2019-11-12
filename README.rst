telegram-bot
============

Overview
--------

Requirements
------------

-  `Python 3 <https://www.python.org/>`__

Installation
------------

.. code:: bash

    git clone https://github.com/dead-beef/telegram-bot
    cd telegram-bot
    pyvenv env
    pyvenv --system-site-packages env
    source env/bin/activate
    pip install -e .[dev]

Testing
-------

.. code:: bash

    ./test

Usage
-----

::

    > python -m bot -h
    usage: __main__.py [-h] [-P POLL] [-p PROXY] [-d DATA_DIR]
                       [-l {critical,error,warning,info,debug}]
                       TOKEN_OR_FILE

    positional arguments:
      TOKEN_OR_FILE         bot token or token file

    optional arguments:
      -h, --help            show this help message and exit
      -P POLL, --poll POLL  polling interval in seconds (default: 0.0)
      -p PROXY, --proxy PROXY
                            proxy (default: socks5://127.0.0.1:9050/ (tor))
      -d DATA_DIR, --data-dir DATA_DIR
                            bot data directory (default: ~/.bot)
      -l {critical,error,warning,info,debug},
      --log-level {critical,error,warning,info,debug}
                            log level (default: info)


Licenses
--------

-  `telegram-bot <https://github.com/dead-beef/telegram-bot/blob/master/LICENSE>`__
