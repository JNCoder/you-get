## Depends ##

* [bottle.py](https://pypi.python.org/pypi/bottle): `pip install bottle`

## Usage ##
```
$ ./you-get-web -h
usage: you-get-web [-h] [--version] [-c CONFIG] [-o OUTPUT_DIR] [-d DATA_DIR]
                   [-s SERVER_TYPE] [-i HOST] [-p PORT] [-D]

you-get rewind playing song by its lyric

optional arguments:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  -c CONFIG, --config CONFIG
                        the config file to load. Default: ${HOME}/.config/you-
                        get/config.ini
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        the directory to save download data
  -d DATA_DIR, --data-dir DATA_DIR
                        the directory to save server data (.sqlite, cookies)
  -s SERVER_TYPE, --server-type SERVER_TYPE
                        the httpd server type. Default: ThreadingWSGIRef
  -i HOST, --host HOST  the host to bind to
  -p PORT, --port PORT  the port to bind to
  -D, --debug           debug run

$ ./you-get-web 
you_get: Output dir: ~/src/you-get
you_get: Data dir: ~/.local/share/you-get/webui
Bottle v0.12.7 server starting up (using WSGIRefServer(server_class=<class 'you_get.webui.webui.App.run_server.<locals>.ThreadingWSGIServer'>))...
Listening on http://localhost:8080/
Hit Ctrl-C to quit.
```

You should visit <http://localhost:8080/html/> for the front page of the simple
builtin Web GUI. Notice the `html/` in the URL.
