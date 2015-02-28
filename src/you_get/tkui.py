#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et

import sys
import os
import time
import threading
import queue
import collections
import sqlite3

import tkinter
import tkinter.font
from tkinter import simpledialog, filedialog, messagebox
from tkinter import ttk

from . import common
from .util import log

LOG_QUEUE_SIZE = 100
MAX_LOG_LINES = 200
NATIVE=sys.getfilesystemencoding()

def num2human(num, kunit=1000):
    """Convert integer to human readable units"""
    if isinstance(num, str) and not num.isdigit():
        return num
    human = ""
    num = float(num)
    if num > 0.01:
        units = ['','K','M','G','T','P','E','Z','Y']
        for x in units:
            if num < kunit:
                human = x
                break
            num /= kunit
    else:
         units = ["m", "μ", "n", "p", "f", "a", "z", "y"]
         for x in units:
             num *= kunit
             if num >= 1.0:
                 human = x
                 break

    return "{:.2f}{}".format(num, human)

def setup_folder():
    """Setup data folder for cross-platform"""
    locations = {
            "win32": "%APPDATA%/unblock_youku",
            "darwin": "$HOME/Library/Application Support/unblock_youku",
            "linux": "$HOME/.local/share/unblock_youku",
            }
    if sys.platform in locations:
        data_folder = locations[sys.platform]
    else:
        data_folder = locations["linux"]

    data_folder = os.path.expandvars(data_folder)
    data_folder = os.path.normpath(data_folder)
    if not os.path.exists(data_folder):
        os.makedirs(data_folder)
    return data_folder
DATA_FOLDER = setup_folder()

class YouGetDB:
    def __init__(self, path=None):
        if path is None:
            db_fname = "you-get-tk.sqlite"
            self.path = os.path.join(DATA_FOLDER, db_fname)
        else:
            self.path = path
        self.db_version = "1.0" # db version
        self.task_tab = "youget_task"
        self.config_tab = "config"
        self.con = None
        self.setup_database()

    def get_version(self):
        """Get db version in the db file"""
        version = None
        try:
            c = self.load_config()
            version = c.get("db_version")
        except sqlite3.OperationalError:
            pass
        return version

    def setup_database(self):
        con = self.con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        file_version = self.get_version()

        if not os.path.exists(self.path):
            con.execute("PRAGMA page_size = 4096;")
        con.execute('''CREATE TABLE if not exists {} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT UNIQUE,
            output_dir TEXT,
            do_playlist BOOLEAN,
            merge BOOLEAN,
            extractor_proxy TEXT,
            stream_id TEXT,
            title TEXT,
            filepath TEXT,
            success INTEGER,
            total_size INTEGER,
            received INTEGER
            )'''.format(self.task_tab))

        #con.execute("DROP TABLE config")
        con.execute('''CREATE TABLE if not exists {} (
            key TEXT UNIQUE,
            value ANY
            )'''.format(self.config_tab))

        if file_version != self.db_version:
            self.save_config({"db_version": self.db_version})
        con.commit()
        return con

    def get_pragma(self, pragma):
        """Get database PRAGMA values"""
        cur = self.con.cursor()
        ret = cur.execute("PRAGMA {};".format(pragma)).fetchall()
        return ret

    def get_task_list(self):
        """Return a list of tasks"""
        cur = self.con.cursor()
        cur.execute("SELECT * FROM {}".format(self.task_tab))
        return list(cur.fetchall())

    def get_task_values(self, origin):
        """Return one task """
        cur = self.con.cursor()
        cur.execute("SELECT * FROM {} where origin=?".format(self.task_tab),
                (origin,))
        return cur.fetchone()

    def set_task_values(self, origin, data_dict):
        cur = self.con.cursor()
        data_dict["origin"] = origin

        keys = data_dict.keys()
        set_list = ["{}=:{}".format(x,x) for x in keys]
        set_str = ", ".join(set_list)

        cur.execute('UPDATE {} SET {} WHERE origin=:origin'.format(
            self.task_tab, set_str), data_dict)
        self.con.commit()

    def delete_task(self, origins):
        if isinstance(origins, str):
            origins = [origins]
        data = [(x,) for x in origins]
        cur = self.con.cursor()
        cur.executemany('DELETE FROM {} WHERE origin=?'.format(
            self.task_tab), data)
        self.con.commit()

    def add_task(self, data_dict):
        # insert sqlite3 with named placeholder
        keys = data_dict.keys()
        keys_tagged = [":"+x for x in keys]
        cur = self.con.cursor()
        cur.execute(''' INSERT INTO {} ({}) VALUES ({}) '''.format(
                    self.task_tab,
                    ", ".join(keys),
                    ", ".join(keys_tagged)),
                data_dict)
        self.con.commit()

    def save_config(self, config):
        cur = self.con.cursor()
        #data = [(x, str(y)) for x, y in config.items()]
        data = config.items()
        cur.executemany('''INSERT OR REPLACE INTO {}
                (key, value)
                VALUES(?, ?)
                '''.format(self.config_tab), data)
        self.con.commit()

    def load_config(self):
        cur = self.con.cursor()
        cur.execute('SELECT key, value FROM {}'.format(self.config_tab))

        return {x[0]: x[1] for x in cur.fetchall()}

    def try_vacuum(self):
        """Try to vacuum the database when meet some threshold"""
        cur = self.con.cursor()
        page_count = self.get_pragma("page_count")[0][0]
        freelist_count = self.get_pragma("freelist_count")[0][0]
        page_size = self.get_pragma("page_size")[0][0]

        #print(page_count, freelist_count, page_count - freelist_count)
        # 25% freepage and 1MB wasted space
        if (float(freelist_count)/page_count > .25
                and freelist_count * page_size > 1024*1024):
            cur.execute("VACUUM;")
            self.commit()

def my_download_main(download, download_playlist, urls, playlist, **kwargs):
    ret = 1
    try:
        common.download_main(download, download_playlist, urls, playlist,
                **kwargs)
    except:
        ret = -1
        log.w("my_download_main() failed")
        log.w(str(sys.exc_info()))
    if "task" in kwargs:
        kwargs["task"].success += ret

class Task:
    """Represent a single download task"""
    def __init__(self, url=None, do_playlist=False, output_dir=".",
            merge=True, extractor_proxy=None, stream_id=None):
        self.origin = url
        self.output_dir = output_dir
        self.do_playlist = do_playlist
        self.merge = merge
        self.extractor_proxy = extractor_proxy
        self.stream_id = stream_id

        self.progress_bar = None
        self.title = None
        self.real_urls = None # a list of urls
        self.filepath = None
        self.thread = None
        self.total_size = 0
        self.received = 0 # keep a record of progress changes
        self.finished = False
        self.success = 0
        self.need_save = False

        self.lock = threading.Lock()

    def get_total(self):
        ret = self.total_size
        if self.progress_bar is not None:
            ret = self.progress_bar.total_size
        return ret

    def changed(self):
        """check if download progress changed since last update"""
        ret = False
        if self.progress_bar:
            ret = self.received != self.progress_bar.received
        return ret

    def update(self):
        if self.progress_bar:
            self.received = self.progress_bar.received
        return self.received

    def percent_done(self):
        total = self.get_total()
        if total <= 0:
            return 0
        percent = float(self.received * 100)/total
        return percent

    def update_task_status(self, urls, filepath, bar):
        """Called by the download_urls function to setup download status
        of the given task"""
        self.real_urls = urls
        self.filepath = filepath
        self.title = os.path.basename(filepath)
        self.progress_bar = bar
        self.set_need_save(True)

    def set_need_save(self, value):
        self.lock.acquire()
        self.need_save = value
        self.lock.release()

    def save_db(self, db):
        current_data = self.get_database_data()
        old_data = db.get_task_values(self.origin)
        new_info = {}
        for k, v in current_data.items():
            if old_data[k] != v:
                new_info[k] = v
        db.set_task_values(self.origin, new_info)
        self.set_need_save(False)

    def get_database_data(self):
        """prepare data for database insertion"""
        keys = [ # Task keys for db
                "origin",
                "output_dir",
                "do_playlist",
                "merge",
                "extractor_proxy",
                "stream_id",
                "title",
                "filepath",
                "success",
                "total_size",
                "received",
                ]
        data = {x: getattr(self, x, None) for x in keys }
        data["total_size"] = self.get_total()
        return data

    def start(self):
        args = (common.any_download, common.any_download_playlist,
                [self.origin], self.do_playlist)
        kwargs = {
                "output_dir": self.output_dir,
                "merge": self.merge,
                "info_only": False,
                "extractor_proxy": self.extractor_proxy,
                "task": self,
                }
        if self.stream_id:
            kwargs["stream_id"] = self.stream_id

        self.finished = False
        t = threading.Thread(target=my_download_main,
                args=args, kwargs=kwargs)
        self.thread = t
        t.download_task = self
        t.daemon = True
        t.name = self.origin # try to save origin URL of the download
        t.start()
        time.sleep(0.1)

class TaskManager:
    def __init__(self, app):
        self.app = app
        self.tasks = {}
        self.task_running_queue = []
        self.task_waiting_queue = collections.deque()
        self.max_task = 5

    def start_download(self, info):
        """Start a download task in a new thread"""
        url = info["url"]

        if not url:
            return
        elif self.has_task(url):
            messagebox.showerror(title="You Get Error",
                    message="Task for the URL: {} already exists".format(url))
            return

        atask = Task(**info)
        self.app.database.add_task(atask.get_database_data())
        self.tasks[url] = atask

        self.app.attach_download_task(atask)
        self.task_waiting_queue.append(atask)
        self.update_task_queue()

    def update_task_queue(self):
        new_run = []
        for atask in self.task_running_queue:
            if atask.thread.is_alive():
                new_run.append(atask)
            else:
                atask.save_db(self.app.database)
                # requeue on failed
                if -3 < atask.success < 0:
                    self.task_waiting_queue.append(atask)
        self.task_running_queue = new_run

        try:
            if len(new_run) < self.max_task:
                available_slot = self.max_task - len(new_run)
                for i in range(available_slot):
                    atask = self.task_waiting_queue.popleft()
                    new_run.append(atask)
                    atask.start()
        except IndexError:
            pass

    def urls2uuid(self, urls):
        return "-".join(urls)

    def has_task(self, origin):
        ret = origin in self.tasks
        return ret

    def get_tasks(self):
        """Get all the tasks"""
        ret = self.tasks.items()
        return ret

    def get_success_tasks(self):
        ret = []
        for origin, atask in self.get_tasks():
            if atask.success > 0:
                ret.append(atask)
        return ret

    def get_failed_tasks(self):
        ret = []
        for origin, atask in self.get_tasks():
            if atask.success < 0:
                ret.append(atask)
        return ret

    def remove_task(self, origin):
        task = self.tasks[origin]
        del self.tasks[origin]
        if task in self.task_waiting_queue:
            self.task_waiting_queue.remove(task)

taskManager=None

class AddTaskDialog(simpledialog.Dialog):
    """Dialog for add new download task"""
    def __init__(self, parent, title=None, settings=None):
        self.settings = settings
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text="URL:").grid(row=0, sticky="e")
        ttk.Label(master, text="Dir:").grid(row=1, sticky="e")
        ttk.Label(master, text="Unblock Youku:").grid(row=2, sticky="e")


        self.e1 = ttk.Entry(master, width=80, exportselection=False)
        self.e2 = ttk.Entry(master, width=80)

        self.unblock_uku_var = tkinter.IntVar()
        self.c1 = ttk.Checkbutton(master, variable=self.unblock_uku_var)

        self.e1.grid(row=0, column=1)
        self.e2.grid(row=1, column=1)
        self.c1.grid(row=2, column=1, sticky="w")

        self.b1 = ttk.Button(master, text="Browse", underline="0",
                command=self.on_browse_directory)
        self.b1.grid(row=1, column=2, padx=6, pady=4)
        self.bind("<Control-b>", self.on_browse_directory)

        # default settings
        if self.settings.get("output_dir"):
            self.set_path(self.settings["output_dir"])
        if self.settings.get("extractor_proxy") == "unblock-youku":
            self.unblock_uku_var.set(1)

        # init URL entry with clipboard content
        try:
            clip_text = self.e1.selection_get()
            if clip_text and clip_text.startswith("http"):
                self.e1.delete(0, "end")
                self.e1.insert(0, clip_text)
                self.e1.select_range(0, "end")
        except tkinter.TclError:
            # nothing in selection
            pass

        self.result = None
        return self.e1 # initial focus

    def on_browse_directory(self, *args):
        """Get directory by GUI"""
        current_dir = self.e2.get()
        output_dir = filedialog.askdirectory(initialdir=current_dir,
                title="You Get Output Directory")
        if output_dir:
            self.set_path(output_dir)

    def set_path(self, path):
        """Set directory for output_dir entry"""
        self.output_dir = path
        self.e2.delete(0, "end")
        self.e2.insert(0, path)

    def apply(self):
        url = self.e1.get()
        output_dir = self.e2.get()
        do_unblock_uku = self.unblock_uku_var.get()
        info = {
                "url": url,
                "output_dir": output_dir,
                "extractor_proxy": "unblock-youku" if do_unblock_uku else "",
                }
        self.result = info
        #print (info) # or something

#d = AddTaskDialog(tkinter.Tk())
class MonkeyFriend:
    """UI object for the thread_monkey_patch.UI_Monkey"""
    def __init__(self, app):
        self.app = app

    def sprint(self, text, *colors):
        lqueue = self.app.log_queue
        lqueue.put((text, colors))

class App(ttk.Frame):
    def __init__(self, parent):
        global taskManager
        super().__init__(parent)
        self.parent = parent
        self.task_manager = TaskManager(self)
        taskManager = self.task_manager
        self.database = YouGetDB()
        self.log_queue = queue.Queue(LOG_QUEUE_SIZE)
        self.setup_ui()
        self.settings = {
                "output_dir": os.path.abspath("."),
                }
        self.load_config()
        self.load_tasks_from_database()

    def setup_ui(self):
        self.parent.title("You-Get")

        paned_window = ttk.PanedWindow(self, orient="vertical")
        self.paned_window = paned_window
        frame_tree = self.frame_tree = ttk.Frame(paned_window)

        # task treeview
        columns=("file", "size", "progress", "origin")
        tree_task = self.tree_task = ttk.Treeview(frame_tree,
                show="headings", columns=columns, displaycolumns=columns[:-1])
        tree_task.tag_configure("done",
                background="sea green", foreground="azure")
        tree_task.tag_configure("failed",
                background="red4", foreground="azure")
        # tree_task.insert("", "end", values=["abs"]*4, tags="live")

        hsb = ttk.Scrollbar(frame_tree, orient="horizontal",
                command=tree_task.xview)
        vsb = ttk.Scrollbar(frame_tree, orient="vertical",
                command=tree_task.yview)
        tree_task.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)

        for t in columns:
            tree_task.heading(t, text=t.title(), anchor="w")

        num_column_width = 60
        tree_task.column("size", stretch=False, width=num_column_width,
                anchor="e")
        tree_task.column("progress", stretch=False, width=num_column_width)
        tree_task.bind("<<TreeviewSelect>>", self.on_treeview_select_changed)

        tree_task.grid(row=0, column=0, sticky="news")
        hsb.grid(row=1, column=0, sticky="ew")
        vsb.grid(row=0, column=1, sticky="ns")
        frame_tree.columnconfigure(0, weight=1)
        frame_tree.rowconfigure(0, weight=1)
        paned_window.add(frame_tree)

        notebook = self.notebook = ttk.Notebook(paned_window)
        # Info Text View
        frame_text = self.frame_text = ttk.Frame(notebook)
        textview = self.textview = tkinter.Text(frame_text, font="monospace",
                wrap="none", undo=False, state="disabled")
        hsb_text = ttk.Scrollbar(frame_text, orient="horizontal",
                command=textview.xview)
        vsb_text = ttk.Scrollbar(frame_text, orient="vertical",
                command=textview.yview)
        textview.configure(xscrollcommand=hsb_text.set,
                yscrollcommand=vsb_text.set)

        hsb_text.grid(row=1, column=0, sticky="ew")
        vsb_text.grid(row=0, column=1, sticky="ns")
        textview.grid(row=0, column=0, in_=frame_text, sticky="news")
        frame_text.columnconfigure(0, weight=1)
        frame_text.rowconfigure(0, weight=1)
        notebook.add(frame_text, text="Detail")

        # Log Text View
        frame_log = self.frame_log = ttk.Frame(notebook)
        text_log = self.text_log = tkinter.Text(frame_log, font="monospace",
                wrap="none", undo=False, state="disabled")
        hsb_log = ttk.Scrollbar(frame_log, orient="horizontal",
                command=text_log.xview)
        vsb_log = ttk.Scrollbar(frame_log, orient="vertical",
                command=text_log.yview)
        text_log.configure(xscrollcommand=hsb_log.set,
                yscrollcommand=vsb_log.set)

        hsb_log.grid(row=1, column=0, sticky="ew")
        vsb_log.grid(row=0, column=1, sticky="ns")
        text_log.grid(row=0, column=0, in_=frame_log, sticky="news")
        frame_log.columnconfigure(0, weight=1)
        frame_log.rowconfigure(0, weight=1)
        notebook.add(frame_log, text="Log")

        text_log.tag_configure("red", foreground="white",
                background="red3")
        text_log.tag_configure("green", foreground="white",
                background="dark green")
        text_log.tag_configure("blue", foreground="white", 
                background="navy")
        text_log.tag_configure("yellow", foreground="white",
                background="gold3")
        text_log.tag_configure("bold", font=tkinter.font.Font(weight="bold"))
        text_log.tag_configure("underline", underline=True)

        paned_window.add(notebook)

        self.setup_menu()

        self.parent.geometry("600x500")
        paned_window.pack(fill="both", expand=True)

        size_grip = self.size_grip = ttk.Sizegrip(frame_text)
        size_grip.grid(row=1, column=1, sticky="ne")

        """
        style = ttk.Style()
        self.style = style
        style.theme_use("default")
        #style.configure("TButton", padding=6)
        """

        self.pack(fill="both", expand=True)

    def setup_menu(self):
        menu_bar = tkinter.Menu(self.parent)
        self.parent.config(menu=menu_bar)
        file_menu = tkinter.Menu(menu_bar, tearoff=False)

        file_menu.add_command(label="New...", underline=0,
                accelerator="Ctrl+N", command=self.on_new_download)
        file_menu.add_command(label="Clear Successed", underline=1,
                command=self.clear_successed_task)
        file_menu.add_command(label="Clear Failed",
                command=self.clear_failed_task)
        submenu = tkinter.Menu(file_menu, tearoff=False)
        submenu.add_command(label="New feed")
        submenu.add_command(label="Bookmarks")
        submenu.add_command(label="Mail")
        #file_menu.add_cascade(label='Import', menu=submenu, underline=0)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", underline=0,
                accelerator="Ctrl+Q", command=self.stop)

        menu_bar.add_cascade(label="File", underline=0, menu=file_menu)
        self.bind_all("<Control-q>", self.stop)
        self.bind_all("<Control-n>", self.on_new_download)

    def load_tasks_from_database(self):
        tasks = self.database.get_task_list()
        for row in tasks:
            #print(dict(zip(row.keys(), list(row))))#; sys.exit()
            atask = Task(url=row["origin"])
            for key in row.keys():
                if hasattr(atask, key):
                    setattr(atask, key, row[key])

            if atask.success < 1:
                atask.success = 0 # reset counter
                self.task_manager.task_waiting_queue.append(atask)
            self.task_manager.tasks[atask.origin] = atask
            self.attach_download_task(atask)

    def on_treeview_select_changed(self, evt):
        tree = self.tree_task
        origins = tree.selection()
        if not origins: return
        origin = origins[0]
        atask = self.task_manager.tasks[origin]
        data = atask.get_database_data()
        data["total"] = num2human(data["total_size"]) + "B"
        data["received"] = num2human(data["received"]) + "B"
        if data["filepath"]:
            data["basename"] = os.path.basename(data["filepath"])
        else:
            data["basename"] = ""
        #print(data)
        msg = """\
      File: {basename:}
       Dir: {output_dir:}
     Total: {total:}
  Received: {received:}

    Format: {stream_id:}
  Playlist: {do_playlist:}
    XProxy: {extractor_proxy:}
    Origin: {origin:}
""".format(**data)

        self.textview.configure(state="normal")
        self.textview.delete("1.0", "end")
        self.textview.insert("1.0", msg)
        self.textview.configure(state="disabled")

    def on_new_download(self, *args):
        """event handler for new download"""
        dialog = AddTaskDialog(self.parent, "New Download", self.settings)
        info = dialog.result
        if info:
            if info["url"].startswith("http"):
                self.settings.update(info)
                self.task_manager.start_download(info)

    def clear_successed_task(self, *args):
        tasks = self.task_manager.get_success_tasks()
        origins = [x.origin for x in tasks]
        for o in origins:
            self.tree_task.delete(o)
            self.task_manager.remove_task(o)
        self.database.delete_task(origins)

    def clear_failed_task(self, *args):
        tasks = self.task_manager.get_failed_tasks()
        origins = [x.origin for x in tasks]
        for o in origins:
            self.tree_task.delete(o)
            self.task_manager.remove_task(o)
        self.database.delete_task(origins)

    def attach_download_task(self, atask, index="end"):
        tree = self.tree_task
        cols = ["-"]*4
        tag = "live"
        if atask.title:
            cols[0] = atask.title
        cols[1] = "{}B".format(num2human(atask.get_total()))
        if atask.success > 0:
            cols[2] = "Done"
            tag = "done"
            atask.finished = True
        else:
            cols[2] = "{:.2f}%".format(atask.percent_done())
        cols[3] = atask.origin
        tree.insert("", index, iid=atask.origin, values=cols, tags=[tag])

    def check_log(self):
        color_codes = {
                1:  "bold",
                4:  "underline",
                31: "red",
                32: "green",
                33: "yellow",
                34: "blue",
                }
        lqueue = self.log_queue
        self.text_log.configure(state="normal")
        empty = lqueue.empty()
        try:
            for i in range(LOG_QUEUE_SIZE):
                text, colors = lqueue.get(block=False)
                tags = tuple([y for x, y in color_codes.items() if x in colors])
                if len(tags) == 0:
                    tags = None
                self.text_log.insert("insert", text+"\n", tags)
        except queue.Empty:
            pass

        # keep upper limit of log lines
        if not empty:
            max_log = MAX_LOG_LINES
            delta = 0 # some extra lines to tolerant
            lindex = self.text_log.index("end")
            line_no, s, w = lindex.partition(".")
            line_no = int(line_no) - 1
            if line_no > max_log + delta :
                cut_off = line_no - max_log
                self.text_log.delete("1.0", "{}.0".format(cut_off))
        self.text_log.configure(state="disabled")

    def update_task(self):
        """Update task status periodically"""
        tree = self.tree_task
        items = self.task_manager.get_tasks()
        for origin, atask in items:
            if atask.need_save == True:
                atask.save_db(self.database)
            if atask.thread is None or atask.finished == True:
                continue
            elif not atask.thread.is_alive():
                if atask.success > 0:
                    tree.item(origin, tags=["done"])
                    tree.set(origin, 2, "Done")
                else:
                    tree.item(origin, tags=["failed"])
                    tree.set(origin, 2, "Failed {}".format(-atask.success))
                atask.finished = True
            elif atask.changed():
                atask.update()
                percent = "{:.2f}%".format(atask.percent_done())
                total_size = num2human(atask.get_total())
                total_size = "{}B".format(total_size)

                tree.set(origin, 0, atask.title)
                tree.set(origin, 1, total_size )
                tree.set(origin, 2, percent)

        self.task_manager.update_task_queue()
        self.check_log()

        self.parent.after(1000, self.update_task) # in ms

    def load_config(self):
        if not self.database:
            self.database = YouGetDB()
        config = self.database.load_config()

        #for k, v in config.items(): log.debug("{}: {} {}".format(k,type(v),v))
        for k, v in config.items():
            if k.startswith("settings_"):
                k, _, _2 = k.partition("_")
                self.settings[k] = v
        if "geometry" in config:
            size, s, pos = config["geometry"].partition("+")
            if not s:
                size, s, pos = config["geometry"].partition("-")

            if s:
                self.parent.geometry(size)
        if "sashpos" in config and config["sashpos"] > 10:
            # FIXME: Don't really work
            # self.paned_window.sashpos(0, config["sashpos"])
            pass

    def save_config(self):
        config = {
                "geometry": self.parent.geometry(),
                "sashpos": self.paned_window.sashpos(0)
                }
        for k, v in self.settings.items():
            if k in {"url",}: continue
            config["settings_" + k] = v
        self.database.save_config(config)

    def start(self):
        self.update_task()
        self.parent.mainloop()

    def stop(self, *args):
        task_items = self.task_manager.get_tasks()
        for origin, atask in task_items:
            atask.save_db(self.database)
        self.save_config()
        self.database.try_vacuum()
        self.quit()

def main(**kwargs):
    def set_stdio_encoding(enc=NATIVE):
        import codecs; stdio = ["stdin", "stdout", "stderr"]
        for x in stdio:
            obj = getattr(sys, x)
            if not obj.encoding: setattr(sys,  x, codecs.getwriter(enc)(obj))
    set_stdio_encoding()

    from . import thread_monkey_patch
    thread_monkey_patch.monkey_patch_common()

    root = tkinter.Tk()
    app = App(root)
    monkey_friend = MonkeyFriend(app)
    thread_monkey_patch.install_ui_monkey(monkey_friend)
    thread_monkey_patch.monkey_patch_log()

    log.i("Data Folder: {}".format(DATA_FOLDER))
    app.start()

if __name__ == '__main__':
    main()

