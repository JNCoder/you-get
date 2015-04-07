#!/usr/bin/python3
# vim:fileencoding=utf-8:sw=4:et

import os
import sys
import json
import queue
import socket

import tkinter
import tkinter.font
from tkinter import simpledialog, filedialog, messagebox
from tkinter import ttk

from . import thread_monkey_patch
from . import task_manager
from .task_manager import TaskStatus
from . import common
from .util import log

APPNAME = "you-get"
LOG_QUEUE_SIZE = 100
MAX_LOG_LINES = 400
LOG_COLOR_CODES = {
        1:  "bold",
        4:  "underline",
        31: "red",
        32: "green",
        33: "yellow",
        34: "blue",
        }

NATIVE=sys.getfilesystemencoding()

socket_timeout = 60
socket.setdefaulttimeout(socket_timeout)

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

class AddTaskDialog(simpledialog.Dialog):
    """Dialog for add new download task"""
    def __init__(self, parent, title=None, settings=None):
        self.settings = settings
        super().__init__(parent, title)

    def wait_window(self, obj):
        """Dialog sometime failed to set the right window size.
        We reset geometry to force autofix widgets
        """
        self.geometry("")
        return super().wait_window(obj)

    def body(self, master):
        """Create body ui for the dialog"""
        ttk.Label(master, text="URL:").grid(row=0, sticky="e")
        ttk.Label(master, text="Dir:").grid(row=1, sticky="e")
        ttk.Label(master, text="Extractor Proxy:").grid(row=2, sticky="e")
        ttk.Label(master, text="Playlist:").grid(row=3, sticky="e")

        # Info Text View
        frame_text = self.frame_text = ttk.Frame(master)
        self.e_url = textview = tkinter.Text(frame_text, font="monospace",
                exportselection=False, wrap="none",
                width=80, height=10,
                )
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

        self.e_dir = ttk.Entry(master, width=80)
        self.e_xproxy = ttk.Entry(master, width=80)

        self.use_xproxy_var = tkinter.IntVar()
        self.use_xproxy_var.trace("w", self.on_use_xproxy_changed)
        self.c_uxproxy = ttk.Checkbutton(master, variable=self.use_xproxy_var)

        self.playlist_var = tkinter.IntVar()
        self.c_playlist = ttk.Checkbutton(master, variable=self.playlist_var)

        padx = 6
        pady = 4
        frame_text.grid(row=0, column=1, padx=padx, pady=pady, sticky="news")
        self.e_dir.grid(row=1, column=1, padx=padx, pady=pady, sticky="ew")
        self.e_xproxy.grid(row=2, column=1, padx=padx, pady=pady, sticky="ew")
        self.c_uxproxy.grid(row=2, column=2, padx=padx, pady=pady, sticky="w")

        self.b_browse = ttk.Button(master, text="Browse", underline="0",
                command=self.on_browse_directory)
        self.b_browse.grid(row=1, column=2, padx=padx, pady=pady)
        self.bind("<Control-b>", self.on_browse_directory)

        self.c_playlist.grid(row=3, column=1, padx=padx, pady=pady, sticky="w")

        # default settings
        if self.settings.get("output_dir", None):
            self.set_path(self.settings["output_dir"])
        if self.settings.get("extractor_proxy", None):
            self.e_xproxy.delete(0, "end")
            self.e_xproxy.insert(0, self.settings["extractor_proxy"])
        if self.settings.get("use_extractor_proxy", False):
            self.use_xproxy_var.set(True)
        else:
            self.use_xproxy_var.set(False)

        # init URL entry with clipboard content
        try:
            clip_text = self.e_url.selection_get().strip()
            if clip_text and "http" in clip_text:
                self.e_url.delete("1.0", "end")
                self.e_url.insert("1.0", clip_text)
                self.e_url.tag_add("sel", "1.0", "end")
        except tkinter.TclError:
            # nothing in clipboard/selection
            pass

        self.result = None

        # Dialog OK by ctrl-return
        self.bind("<Control-Return>", super().ok)

        return self.e_url # initial focus

    def ok(self, event=None):
        """simpledialog.Dialog catch "<Return>" event as OK."""
        if event is not None and event.widget == self.e_url:
            return 'break'
        else:
            return super().ok(event)

    def on_use_xproxy_changed(self, *args):
        if self.use_xproxy_var.get():
            self.e_xproxy.configure(state="normal")
        else:
            self.e_xproxy.configure(state="disabled")

    def on_browse_directory(self, *args):
        """Get directory by GUI"""
        current_dir = self.e_dir.get()
        output_dir = filedialog.askdirectory(initialdir=current_dir,
                title="You-Get Output Directory")
        if output_dir:
            self.set_path(output_dir)

    def set_path(self, path):
        """Set directory for output_dir entry"""
        self.output_dir = path
        self.e_dir.delete(0, "end")
        self.e_dir.insert(0, path)

    def apply(self):
        """Once done, collect use input"""
        url = self.e_url.get("1.0", "end").strip()
        output_dir = self.e_dir.get()
        extractor_proxy = self.e_xproxy.get()
        use_xproxy = True if self.use_xproxy_var.get() else False
        do_playlist = True if self.playlist_var.get() else False
        info = {
                "url": url,
                "output_dir": output_dir,
                "extractor_proxy": extractor_proxy,
                "use_extractor_proxy": use_xproxy,
                "do_playlist": do_playlist,
                }
        self.result = info
        #print (info) # or something

#d = AddTaskDialog(tkinter.Tk())
class MonkeyFriend(thread_monkey_patch.UIFriend):
    """UI object for the thread_monkey_patch.UI_Monkey"""
    def __init__(self, app):
        self.app = app

    def sprint(self, text, *colors):
        lqueue = self.app.log_queue
        lqueue.put((text, colors))

class ColumnIndex:
    """A class holding map of column label to index, for tkinter.treeview"""
    def __init__(self, cols):
        for i, k in enumerate(cols):
            setattr(self, k, i)
        self._len = len(cols)

    def __len__(self):
        return self._len

class App(ttk.Frame):
    """main application"""
    db_fname = "you-get-tk.sqlite"
    cookie_fname = "you-get-tk-cookies.txt"
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.cookiejar = None
        self.timeout_update_task = 3000 # in mseconds
        self.timeout_update_gui = 1000

        self.task_manager = task_manager.TaskManager(self)
        self.data_folder = os.path.join(
                task_manager.setup_data_folder(APPNAME), "tkui")
        log.i("Data Folder: {}".format(self.data_folder))
        self.log_queue = queue.Queue(LOG_QUEUE_SIZE)

        self.setup_ui()
        self.settings = {
                "output_dir": os.path.abspath("."),
                }
        self.database = self.new_database()
        self.parent.after(100, self.delay_init)

    def new_database(self):
        database = task_manager.YouGetDB(self.db_fname, self.data_folder)
        return database

    def delay_init(self):
        """Delay load slow stuff after GUI Window shows up"""
        self.load_config()
        self.setup_cookiejar()
        self.load_tasks_from_database()

    def setup_ui(self):
        self.parent.title("You-Get")

        paned_window = ttk.PanedWindow(self, orient="vertical")
        self.paned_window = paned_window
        frame_tree = self.frame_tree = ttk.Frame(paned_window)

        # task treeview
        columns=("file", "size", "speed", "progress", "origin")
        self.tree_cols = ColumnIndex(columns)

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

        for t in ["file"]:
            tree_task.heading(t, text=t.title(), anchor="w")
        for t in ["size", "speed", "progress"]:
            tree_task.heading(t, text=t.title(), anchor="e")

        num_column_width = 65
        speed_column_width = int(num_column_width * 6/5)
        tree_task.column("size", stretch=False, width=num_column_width,
                anchor="e")
        tree_task.column("progress", stretch=False, width=num_column_width,
                anchor="e")
        tree_task.column("speed", stretch=False, width=speed_column_width,
                anchor="e")
        tree_task.bind("<<TreeviewSelect>>", self.on_treeview_select_changed)
        tree_task.bind("<Control-r>", self.restart_selected_task)
        tree_task.bind("<Delete>", self.remove_selected_task)

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

        # File menu
        file_menu = tkinter.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="New...", underline=0,
                accelerator="Ctrl+N", command=self.on_new_download)
        """
        submenu = tkinter.Menu(file_menu, tearoff=False)
        submenu.add_command(label="New feed")
        submenu.add_command(label="Bookmarks")
        submenu.add_command(label="Mail")
        file_menu.add_cascade(label='Import', menu=submenu, underline=0)
        """
        file_menu.add_separator()
        file_menu.add_command(label="Quit", underline=0,
                accelerator="Ctrl+Q", command=self.stop)

        menu_bar.add_cascade(label="File", underline=0, menu=file_menu)

        # Task menu
        task_menu = tkinter.Menu(menu_bar, tearoff=False)
        task_menu.add_command(label="Re-Start", underline=0,
                accelerator="Ctrl+R",
                command=self.restart_selected_task)
        task_menu.add_command(label="Remove", underline=1,
                accelerator="Del",
                command=self.remove_selected_task)
        task_menu.add_separator()
        task_menu.add_command(label="Clear Successed", underline=7,
                command=self.clear_successed_task)
        task_menu.add_command(label="Clear Failed", underline=7,
                command=self.clear_failed_task)
        menu_bar.add_cascade(label="Task", underline=0, menu=task_menu)

        self.bind_all("<Control-q>", self.stop)
        self.bind_all("<Control-n>", self.on_new_download)

    def load_tasks_from_database(self):
        tasks = self.task_manager.load_tasks_from_database()
        for atask in tasks:
            self.attach_download_task(atask)

    def on_treeview_select_changed(self, evt):
        tree = self.tree_task
        origins = tree.selection()
        if not origins: return
        origin = origins[0]
        atask = self.task_manager.get_task(origin)
        data = atask.get_database_data()
        data["total"] = num2human(data["total_size"]) + "B"
        data["received"] = num2human(data["received"]) + "B"

        data.update(data["options"])

        bool_keys = ["do_playlist", "merge"]
        for k in bool_keys:
            data[k] = "ON" if data[k] else "OFF"
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
    Status: {status:}

    Format: {stream_id:}
  Playlist: {do_playlist:}
    XProxy: {extractor_proxy:}
    Origin: {origin:}
""".format(**data)

        if data["playlist"]:
            playlist = sorted(data["playlist"])
            indent = " " * 12
            playlist = ("\n" + indent).join(playlist)
            msg = """{}
     Files: {}\n""".format(msg, playlist)

        self.textview.configure(state="normal")
        self.textview.delete("1.0", "end")
        self.textview.insert("1.0", msg)
        self.textview.configure(state="disabled")

    def on_new_download(self, *args):
        """event handler for new download"""
        dialog = AddTaskDialog(self.parent, "You-Get New Download",
                self.settings)
        info = dialog.result
        if info and "http" in info["url"]:
            self.settings.update(info)
            err_msg = []

            # clean up options
            if not info["use_extractor_proxy"]:
                info["extractor_proxy"] = None
            del info["use_extractor_proxy"]

            urls = info["url"].splitlines()
            task_list = []
            for url in urls:
                url = url.strip()
                if not url.startswith("http"):
                    continue
                dinfo = info.copy()
                dinfo["url"] = url.strip()
                try:
                    atask = self.task_manager.start_download(dinfo)
                    self.attach_download_task(atask)
                    task_list.append(atask)
                except task_manager.TaskError as err:
                    err_msg.append(str(err))
            if task_list:
                self.task_manager.queue_tasks(task_list)
            if err_msg:
                msg = "\n".join(err_msg)
                messagebox.showerror(title="You-Get Error", message=msg)

    def restart_selected_task(self, *args):
        origins = self.tree_task.selection()
        if not origins: return
        self.task_manager.queue_tasks(origins)

    def remove_tasks(self, origins):
        """remove tasks with the given origins"""
        for o in origins:
            self.tree_task.delete(o)
        self.task_manager.remove_tasks(origins)

    def remove_selected_task(self, *args):
        origins = self.tree_task.selection()
        if not origins: return
        self.remove_tasks(origins)

    def clear_successed_task(self, *args):
        tasks = self.task_manager.get_successed_tasks()
        origins = [x.origin for x in tasks]
        self.remove_tasks(origins)

    def clear_failed_task(self, *args):
        tasks = self.task_manager.get_failed_tasks()
        origins = [x.origin for x in tasks]
        self.remove_tasks(origins)

    def attach_download_task(self, atask, index="end"):
        """Attach a download task to the treeview"""
        tree = self.tree_task
        tc = self.tree_cols
        cols = ["-"]*len(tc)
        tag = "live"
        if atask.title:
            cols[tc.file] = atask.title
        cols[tc.size] = "{}B".format(num2human(atask.get_total()))
        if atask.success > 0:
            cols[tc.progress] = "Done"
            tag = "done"
            #atask.status = "finished"
        else:
            cols[tc.progress] = "{:.2f}%".format(atask.percent_done())
        cols[tc.origin] = atask.origin
        tree.insert("", index, iid=atask.origin, values=cols, tags=[tag])
        tree.see(atask.origin)

    def update_task(self):
        """Update task status"""

        # need to track changed task before doing update_task_queue()
        tasks = self.task_manager.get_tasks()
        changed_tasks = set([x for x in tasks if x.changed()])
        self.task_manager.update_tasks()

        tc = self.tree_cols
        tree = self.tree_task
        for atask in tasks:
            origin = atask.origin
            if atask.status in {TaskStatus.Create, TaskStatus.Done}:
                continue
            elif atask.thread is None and atask.status == TaskStatus.Stop:
                if atask.success > 0:
                    tree.item(origin, tags=["done"])
                    tree.set(origin, tc.progress, "Done")
                else:
                    tree.item(origin, tags=["failed"])
                    tree.set(origin, tc.progress,
                            "Failed {}".format(-atask.success))
                # one last update
                total_size = num2human(atask.get_total())
                total_size = "{}B".format(total_size)
                speed = "-"

                tree.set(origin, tc.file, atask.title)
                tree.set(origin, tc.size, total_size )
                tree.set(origin, tc.speed, speed)

                atask.status = TaskStatus.Done
            elif atask in changed_tasks:
                percent = "{:.2f}%".format(atask.percent_done())
                total_size = num2human(atask.get_total())
                total_size = "{}B".format(total_size)
                speed = "{}B/s".format( num2human(atask.speed) )

                if atask.success != 0: # reset tag
                    item = tree.item(origin)
                    tags = item["tags"]
                    if "failed" in tags or "done" in tags:
                        tree.item(origin, tags=["live"])

                tree.set(origin, tc.file, atask.title)
                tree.set(origin, tc.size, total_size )
                tree.set(origin, tc.speed, speed)
                tree.set(origin, tc.progress, percent)
            else:
                # nothing changed
                speed = tree.set(origin, tc.speed)
                speed_0 = "0B/s"
                if speed not in {speed_0, "-"}:
                    tree.set(origin, tc.speed, speed_0)

    def check_log(self):
        """Check log_queue and output log messages"""
        lqueue = self.log_queue
        self.text_log.configure(state="normal")
        empty = lqueue.empty()
        try:
            for i in range(LOG_QUEUE_SIZE):
                text, colors = lqueue.get(block=False)
                tags = tuple([y for x, y in LOG_COLOR_CODES.items()
                    if x in colors])
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

    def load_config(self):
        if not self.database:
            self.database = task_manager.YouGetDB(self.db_fname,
                    self.data_folder)
        config = self.database.load_config()

        #for k, v in config.items(): log.debug("{}: {} {}".format(k,type(v),v))
        for k, v in config.items():
            if k.startswith("settings_"):
                prefix, _, k = k.partition("_")
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
            if k in {"url", "do_playlist"}: continue
            config["settings_" + k] = v
        self.database.save_config(config)

    def periodic_gui_update(self):
        timeout = self.timeout_update_gui
        self.check_log()
        self.parent.after(timeout, self.periodic_gui_update)

    def periodic_task_update(self):
        """Do some periodic update work"""
        timeout = self.timeout_update_task # in mseconds
        self.update_task()

        self.parent.after(timeout, self.periodic_task_update)

    def setup_cookiejar(self):
        """setup cookie jar
        It seems cookiejar use some kind Lock, so assume we are thread safe"""
        from http import cookiejar
        cookie_path = os.path.join(self.data_folder, self.cookie_fname)
        cookies_txt = cookiejar.MozillaCookieJar(cookie_path)
        try:
            cookies_txt.load()
        except OSError:
            pass # file not found
        common.cookies_txt = cookies_txt
        self.cookiejar = cookies_txt

    def start(self):
        self.periodic_task_update()
        self.periodic_gui_update()
        self.parent.mainloop()

    def stop(self, *args):
        self.save_config() # need to done before mainloop stop
        self.parent.withdraw() # hide main window immediately
        self.parent.quit()

        self.cookiejar.save()
        database = self.database
        task_items = self.task_manager.get_running_tasks()
        for atask in task_items:
            atask.save_db(database)
        task_items = self.task_manager.get_tasks()
        for atask in task_items:
            if atask.save_event.is_set():
                atask.save_db(database)
        self.database.try_vacuum()
        self.parent.destroy() # quit() won't do when other dialogs were up.

def main(**kwargs):
    def set_stdio_encoding(enc=NATIVE):
        import codecs; stdio = ["stdin", "stdout", "stderr"]
        for x in stdio:
            obj = getattr(sys, x)
            if not obj.encoding: setattr(sys,  x, codecs.getwriter(enc)(obj))
    set_stdio_encoding()

    thread_monkey_patch.monkey_patch_urllib_request()
    thread_monkey_patch.monkey_patch_common()

    root = tkinter.Tk()
    app = App(root)
    monkey_friend = MonkeyFriend(app)
    thread_monkey_patch.install_ui_monkey(monkey_friend)
    thread_monkey_patch.monkey_patch_log()

    app.start()

if __name__ == '__main__':
    main()

