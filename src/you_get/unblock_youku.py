#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et

import sys
import os
import io
import re
try:
    from urllib import request
    from urllib import parse as urlparse
except:
    import urllib2 as request
    import urlparse

EXPIRE_TIMEOUT = 60*60*24*7 # one week

if sys.platform == "win32":
    data_folder = os.path.expandvars("%APPDATA%/unblock_youku")
elif sys.platform == "darwin":
    data_folder = os.path.expandvars("$HOME/Library/Caches/unblock_youku")
elif sys.platform.startswith("linux"):
    data_folder = os.path.expandvars("$HOME/.cache/unblock_youku")
else:
    data_folder = os.path.expandvars("$HOME/.cache/unblock_youku")
#print(data_folder); sys.exit()

data_folder = os.path.normpath(data_folder)
if not os.path.exists(data_folder):
    os.makedirs(data_folder)
data_path = os.path.join(data_folder, "urls.js")
pac_path = os.path.join(data_folder, "proxy.pac")
#print(data_path)

UKU_DATA_URL = "https://raw.githubusercontent.com/zhuzhuor/Unblock-Youku/master/shared/urls.js"
UKU_PAC_URL = "http://dns.umbridges2014.com/proxy.pac"

c_comments = re.compile(r"(?<!:)//")
pac_pattern = re.compile(r'_proxy_str="PROXY ([^"]*)"')

class _uObject:
    pass

class UnblockUkuFilter:
    def __init__(self):
        self.expire_timeout = EXPIRE_TIMEOUT
        self.url_filters = None # the unblock youku url filters
        self.proxy_str = None
        self.get_uku_data()

    def parse_uku(self, text):
        new_lines = []
        for line in text.splitlines():
            if line.startswith("function "):
                break
            if line.startswith(("/*", "//", " *")):
                continue
            if line.startswith(("var ",)):
                continue
            parts = c_comments.split(line)
            #print(parts)
            if len(parts) > 1:
                line = parts[0]
            line = line.rstrip(";")
            if line.strip():
                new_lines.append(line)

        text_new = ("\n".join(new_lines))
        #print(text_new)

        unblock_youku = _uObject()
        data = {"unblock_youku": unblock_youku}
        exec(text_new, data)
        #print(unblock_youku.common_urls)
        return unblock_youku

    def load_local_data(self, dpath=data_path):
        """load filter file cotent from local cache"""
        ret = None
        expired = True

        if os.path.exists(dpath) and os.path.getsize(dpath) > 0:
            mtime = os.path.getmtime(dpath)
            import time
            now = time.time()
            if  self.expire_timeout < 0 or mtime + self.expire_timeout > now:
                expired = False

        if expired == False:
            ret = io.open(dpath, encoding="utf-8").read()
        return ret

    def get_ubu_urls(self, url=UKU_DATA_URL, dpath=data_path):
        """Get url filters text"""
        content = self.load_local_data(dpath)
        if content is not None:
            return content

        fd = request.urlopen(url)
        content = fd.read()
        fd.close()
        if content:
            content = content.decode("utf-8")
            fdw = io.open(dpath, "w", encoding="utf-8")
            fdw.write(content)
            fdw.close()
        return content

    def get_ubu_proxy_url(self):
        content = self.get_ubu_urls(UKU_PAC_URL, dpath=pac_path)
        if not content: return None
        ret = None
        match = pac_pattern.search(content)

        if match is not None:
            ret = match.group(1)
        self.proxy_str = ret
        return ret

    def get_uku_data(self):
        content = self.get_ubu_urls()
        result = None
        if content:
            data = self.parse_uku(content)
            #print(data.common_urls)
            # convert shell pattern to regex
            import fnmatch
            for attr in dir(data):
                if attr.endswith("_urls"):
                    filter_list = getattr(data, attr)
                    areg = [fnmatch.translate(x) for x in filter_list]
                    setattr(data, attr, areg)

            #print(data.common_urls)
            # create all in one big regex objects
            join_black = data.common_urls + data.server_extra_urls
            join_white = data.server_whitelist_urls

            ndata = _uObject()
            ndata.join_black = re.compile("|".join(join_black))
            ndata.join_white = re.compile("|".join(join_white))
            result = ndata

        self.url_filters = result
        self.proxy_str = self.get_ubu_proxy_url()
        return result

    def do_proxy(self, url):
        if self.url_filters is None:
            self.get_uku_data()
        ret = False
        if not url.startswith(("http://", "https://")):
            return ret
        if self.url_filters.join_white.match(url) is not None:
            return False
        if self.url_filters.join_black.match(url) is not None:
            ret = True
        return ret

class UnblockYoukuProxy(request.ProxyHandler):
    def __init__(self, proxies=None):
        self.uku_filter = UnblockUkuFilter()

        proxies = {
                "http": self.uku_filter.proxy_str,
                "https": self.uku_filter.proxy_str,
                }
        request.ProxyHandler.__init__(self, proxies)

    def should_proxy(self, req):
        ret = False
        orig_type = req.type
        if orig_type in ["http", "https"]:
            u = req.get_full_url()
            if self.uku_filter.do_proxy(u) == True:
                ret = True
        return ret

    def proxy_open(self, req, proxy, type):
        if self.should_proxy(req) == True:
            print("proxy with: {}".format(proxy))
            request.ProxyHandler.proxy_open(self, req, proxy, type)
        else:
            print("no proxy.")
            return None

def main():
    #fname = sys.argv[1]
    #text = io.open(fname, encoding="utf-8").read()
    uku = UnblockUkuFilter()
    #data = uku.parse_uku(text)
    print(uku.proxy_str)

if __name__ == "__main__":
    main()

