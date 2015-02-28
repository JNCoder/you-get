#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et
"""
Monkey patch modules to make them thread aware.

Since `urllib` is not thread safe, .common will not be
thread safe before and after monkey patched.
"""

import sys
import os
import threading

from . import common
from .common import tr, urls_size, get_filename, url_save, url_save_chunked

Origins = {} # kept original functions

def tkui_download_urls(urls, title, ext, total_size, output_dir='.', refer=None, merge=True, faker=False):
    """download_urls() which register progress bar to taskManager"""
    assert urls
    force=False

    if not total_size:
        try:
            total_size = urls_size(urls)
        except:
            import traceback
            import sys
            traceback.print_exc(file = sys.stdout)
            pass

    title = tr(get_filename(title))

    filename = '%s.%s' % (title, ext)
    filepath = os.path.join(output_dir, filename)

    bar = SimpleProgressBar(total_size, len(urls))

    thread_me = threading.current_thread()
    #print("download task of current thread:", thread_me.download_task)
    try:
        thread_me.download_task.update_task_status(urls, filepath, bar)
    except AttributeError:
        pass

    if total_size:
        if not force and os.path.exists(filepath) and os.path.getsize(filepath) >= total_size * 0.9:
            print('Skipping %s: file already exists' % filepath)
            print()
            bar.done()
            return

    if len(urls) == 1:
        url = urls[0]
        print('Downloading %s ...' % tr(filename))
        url_save(url, filepath, bar, refer = refer, faker = faker)
        bar.done()
    else:
        parts = []
        print('Downloading %s.%s ...' % (tr(title), ext))
        for i, url in enumerate(urls):
            filename = '%s[%02d].%s' % (title, i, ext)
            filepath = os.path.join(output_dir, filename)
            parts.append(filepath)
            #print 'Downloading %s [%s/%s]...' % (tr(filename), i + 1, len(urls))
            bar.update_piece(i + 1)
            url_save(url, filepath, bar, refer = refer, is_part = True, faker = faker)
        bar.done()

        if not merge:
            print()
            return
        if ext in ['flv', 'f4v']:
            try:
                from .processor.ffmpeg import has_ffmpeg_installed
                if has_ffmpeg_installed():
                    from .processor.ffmpeg import ffmpeg_concat_flv_to_mp4
                    ffmpeg_concat_flv_to_mp4(parts, os.path.join(output_dir, title + '.mp4'))
                else:
                    from .processor.join_flv import concat_flv
                    concat_flv(parts, os.path.join(output_dir, title + '.flv'))
            except:
                raise
            else:
                for part in parts:
                    os.remove(part)

        elif ext == 'mp4':
            try:
                from .processor.ffmpeg import has_ffmpeg_installed
                if has_ffmpeg_installed():
                    from .processor.ffmpeg import ffmpeg_concat_mp4_to_mp4
                    ffmpeg_concat_mp4_to_mp4(parts, os.path.join(output_dir, title + '.mp4'))
                else:
                    from .processor.join_mp4 import concat_mp4
                    concat_mp4(parts, os.path.join(output_dir, title + '.mp4'))
            except:
                raise
            else:
                for part in parts:
                    os.remove(part)

        else:
            print("Can't merge %s files" % ext)

    print()

def tkui_download_urls_chunked(urls, title, ext, total_size, output_dir='.', refer=None, merge=True, faker=False):
    """download_urls_chunked() which register progress bar to taskManager"""
    assert urls
    force = False

    assert ext in ('ts')

    title = tr(get_filename(title))

    filename = '%s.%s' % (title, 'ts')
    filepath = os.path.join(output_dir, filename)

    bar = SimpleProgressBar(total_size, len(urls))
    thread_me = threading.current_thread()
    try:
        thread_me.download_task.update_task_status(urls, filepath, bar)
    except AttributeError:
        pass

    if total_size:
        if not force and os.path.exists(filepath[:-3] + '.mkv'):
            print('Skipping %s: file already exists' % filepath[:-3] + '.mkv')
            print()
            bar.done()
            return

    if len(urls) == 1:
        parts = []
        url = urls[0]
        print('Downloading %s ...' % tr(filename))
        filepath = os.path.join(output_dir, filename)
        parts.append(filepath)
        url_save_chunked(url, filepath, bar, refer = refer, faker = faker)
        bar.done()

        if not merge:
            print()
            return
        if ext == 'ts':
            from .processor.ffmpeg import has_ffmpeg_installed
            if has_ffmpeg_installed():
                from .processor.ffmpeg import ffmpeg_convert_ts_to_mkv
                if ffmpeg_convert_ts_to_mkv(parts, os.path.join(output_dir, title + '.mkv')):
                    for part in parts:
                        os.remove(part)
                else:
                    os.remove(os.path.join(output_dir, title + '.mkv'))
            else:
                print('No ffmpeg is found. Conversion aborted.')
        else:
            print("Can't convert %s files" % ext)
    else:
        parts = []
        print('Downloading %s.%s ...' % (tr(title), ext))
        for i, url in enumerate(urls):
            filename = '%s[%02d].%s' % (title, i, ext)
            filepath = os.path.join(output_dir, filename)
            parts.append(filepath)
            #print 'Downloading %s [%s/%s]...' % (tr(filename), i + 1, len(urls))
            bar.update_piece(i + 1)
            url_save_chunked(url, filepath, bar, refer = refer, is_part = True, faker = faker)
        bar.done()

        if not merge:
            print()
            return
        if ext == 'ts':
            from .processor.ffmpeg import has_ffmpeg_installed
            if has_ffmpeg_installed():
                from .processor.ffmpeg import ffmpeg_concat_ts_to_mkv
                if ffmpeg_concat_ts_to_mkv(parts, os.path.join(output_dir, title + '.mkv')):
                    for part in parts:
                        os.remove(part)
                else:
                    os.remove(os.path.join(output_dir, title + '.mkv'))
            else:
                print('No ffmpeg is found. Merging aborted.')
        else:
            print("Can't merge %s files" % ext)

    print()

class SimpleProgressBar:
    def __init__(self, total_size, total_pieces=1):
        self.total_size = total_size
        self.total_pieces = total_pieces
        self.current_piece = 1
        self.received = 0
        self.finished = False

    def update(self):
        pass
    def update_received(self, n):
        self.received += n
        self.update()
    def update_piece(self, n):
        self.current_piece = n
    def done(self):
        self.finished = True
        self.received = self.total_size
        self.current_piece = self.total_pieces
        self.update()

def monkey_patch_common():
    """Replace common.download_urls() with our own functions"""
    m = {}
    m["download_urls"] = common.download_urls
    m["download_urls_chunked"] = common.download_urls_chunked
    Origins["common"] = m

    common.download_urls = tkui_download_urls
    common.download_urls_chunked = tkui_download_urls_chunked

class UIMonkey:
    """Monkey patch functions with an UI object"""
    def __init__(self, ui_obj):
        self.ui_obj = ui_obj

    def sprint(self, text, *colors):
        ret = Origins["util.log"]["sprint"](text, *colors)

        try:
            self.ui_obj.sprint(text, *colors)
        except:
            sys.stderr.write(sys.exc_info())
            sys.stderr.flush()
        return ret

UI_Monkey = None

def install_ui_monkey(ui_obj):
    """Supply a GUI object to UIMonkey"""
    global UI_Monkey
    if UI_Monkey is None:
        UI_Monkey = UIMonkey(ui_obj)

def monkey_patch_log():
    from .util import log
    m = {}
    m["sprint"] = log.sprint
    Origins["util.log"] = m

    log.sprint = UI_Monkey.sprint

