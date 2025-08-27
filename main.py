import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import json
import DataMeasurer as dm
import numpy as np
import os
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import threading
import time
import io
import sys
import queue

# --- Detect if we are in a PyInstaller-built executable ---
IS_FROZEN = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')
if IS_FROZEN:
    # Suppress print() and error output in GUI executable
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')

# =========================
# Shared: Spectrograph only
# =========================

# --- Globals for plotting and scan control (spectrograph mode) ---
plot_fig = None
plot_ax = None
plot_line = None
scan_data = []
scan_wls = []
scan_stopped = False

# --- Backend subprocess call for spectrograph (unchanged) ---
def run(command, *args):
    cmd = [
        r".venv313-32\Scripts\python.exe",
        "controller\spectrograph_command.py",
        command
    ] + list(map(str, args))

    startupinfo = None
    if IS_FROZEN:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=45,
            startupinfo=startupinfo
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"MS260i command '{command}' timed out.")

    if result.returncode != 0:
        raise RuntimeError(f"Error running MS260i: {result.stderr.strip()}")

    output = result.stdout.strip()
    print(output)  # Safe in dev, suppressed in packaged GUI
    return output

# =========================
# Helpers: line-based IPC
# =========================

class _LineProcess:
    """
    Minimal line-oriented subprocess wrapper (stdin/stdout).
    Used for th260_helper.exe (x64) and stage_helper.exe (x64).
    """
    def __init__(self, exe_path):
        self.exe_path = exe_path
        self.p = subprocess.Popen(
            [exe_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", bufsize=1
        )
        greet = self._readline(timeout=10.0)
        if not greet.startswith("OK"):
            raise RuntimeError(f"{os.path.basename(exe_path)} not ready: {greet}")

    def _readline(self, timeout=10.0):
        q = queue.Queue()
        def reader():
            q.put(self.p.stdout.readline())
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        try:
            line = q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"No response from {os.path.basename(self.exe_path)}")
        if not line:
            raise RuntimeError(f"{os.path.basename(self.exe_path)} closed")
        return line.rstrip("\r\n")

    def send(self, line, timeout=10.0):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        resp = self._readline(timeout=timeout)
        if not resp.startswith("OK"):
            raise RuntimeError(resp)
        return resp

    def close(self):
        try:
            self.send("exit")
        except Exception:
            pass
        try:
            self.p.terminate()
        except Exception:
            pass

class TH260Client:
    """Wrapper for th260_helper.exe"""
    def __init__(self, exe_path):
        self.proc = _LineProcess(exe_path)

    def init(self, binning=1, offset_ps=0, sync_div=1, sync_offset_ps=25000):
        self.proc.send(f"init {binning} {offset_ps} {sync_div} {sync_offset_ps}", timeout=20.0)

    def info(self):
        r = self.proc.send("info")
        parts = dict(kv.split("=") for kv in r[3:].split())
        return float(parts["RES"]), int(parts["CH"]), int(parts["LEN"])

    def acquire(self, tacq_ms=1000):
        r = self.proc.send(f"acquire {tacq_ms}", timeout=max(10.0, tacq_ms/1000.0 + 5.0))
        meta = dict(kv.split("=") for kv in r[3:].split()[1:])
        ch, ln, nbytes = int(meta["CH"]), int(meta["LEN"]), int(meta["BYTES"])
        # Next line is base64 payload
        b64 = self.proc._readline(timeout=10.0)
        raw = subprocess.base64.b64decode(b64.encode("ascii")) if hasattr(subprocess, "base64") else __import__("base64").b64decode(b64.encode("ascii"))
        arr = np.frombuffer(raw, dtype=np.uint32)
        if arr.size != ch * ln:
            raise RuntimeError("TH260 size mismatch")
        return arr.reshape((ch, ln))

    def close(self):
        self.proc.close()

class StageClient:
    """Wrapper for stage_helper.exe"""
    def __init__(self, exe_path):
        self.proc = _LineProcess(exe_path)

    def open(self, serial_x, serial_y, vmax_tenths=750):
        self.proc.send(f"open {serial_x} {serial_y} {vmax_tenths}", timeout=10.0)

    def move_ix(self, ix, iy, width, height):
        self.proc.send(f"move_ix {ix} {iy} {width} {height}")

    def setdac(self, vx_code, vy_code):
        self.proc.send(f"setdac {vx_code} {vy_code}")

    def disable(self):
        try:
            self.proc.send("disable")
        except Exception:
            pass

    def close(self):
        try:
            self.disable()
        finally:
            self.proc.close()

# =========================
# Spectrograph GUI (as-is)
# =========================

class SpectrographFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.build_ui()

    def build_ui(self):
        global plot_fig, plot_ax, plot_line

        # --- Scan Settings Section ---
        scan_frame = ttk.LabelFrame(self, text="Scan Settings", padding=10)
        scan_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        ttk.Label(scan_frame, text="Start Wavelength (nm):").grid(row=0, column=0, sticky="e")
        ttk.Label(scan_frame, text="End Wavelength (nm):").grid(row=1, column=0, sticky="e")
        ttk.Label(scan_frame, text="Step Count:").grid(row=2, column=0, sticky="e")
        ttk.Label(scan_frame, text="Save Location:").grid(row=3, column=0, sticky="e")

        self.start_entry = ttk.Entry(scan_frame)
        self.end_entry = ttk.Entry(scan_frame)
        self.step_entry = ttk.Entry(scan_frame)
        self.save_location_entry = ttk.Entry(scan_frame, width=30)

        self.start_entry.grid(row=0, column=1, padx=5, pady=5)
        self.end_entry.grid(row=1, column=1, padx=5, pady=5)
        self.step_entry.grid(row=2, column=1, padx=5, pady=5)
        self.save_location_entry.grid(row=3, column=1, padx=5, pady=5)

        ttk.Button(scan_frame, text="Browse...", command=self.browse_save_location).grid(row=3, column=2, padx=5)

        ttk.Button(scan_frame, text="Start Scan", command=self.start_scan_with_plot).grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(scan_frame, text="Stop Scan", command=self.stop_scan).grid(row=4, column=2, pady=10)

        # --- Wavelength Controls Section ---
        wl_frame = ttk.LabelFrame(self, text="Wavelength Control", padding=10)
        wl_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        ttk.Label(wl_frame, text="Set Wavelength:").grid(row=0, column=0, sticky="e")
        self.wl_entry = ttk.Entry(wl_frame); self.wl_entry.grid(row=0, column=1, padx=5)
        ttk.Button(wl_frame, text="Set", command=self.set_wavelength).grid(row=0, column=2, padx=5)
        ttk.Button(wl_frame, text="Get Wavelength", command=self.get_wav).grid(row=1, column=0, columnspan=3, pady=5)
        self.current_wavelength_label = ttk.Label(wl_frame, text="Current Wavelength: --")
        self.current_wavelength_label.grid(row=2, column=0, columnspan=3)

        # --- Plot Area ---
        plot_frame = ttk.LabelFrame(self, text="Live Plot", padding=10)
        plot_frame.grid(row=0, column=1, rowspan=3, padx=10, pady=10, sticky="nsew")

        # Initialize plot
        if plot_fig is None:
            plot_fig, plot_ax = plt.subplots()
            plot_line, = plot_ax.plot([], [], 'b-')
            plot_ax.set_xlabel("Wavelength (nm)")
            plot_ax.set_ylabel("Lock-In Amp Voltage")
            plot_ax.set_title("Live Data")
            plot_ax.grid(True)
            canvas = FigureCanvasTkAgg(plot_fig, master=plot_frame)
            canvas.get_tk_widget().pack(fill="both", expand=True)
            plot_fig.tight_layout()
        else:
            plot_ax.clear()
            plot_ax.set_xlabel("Wavelength (nm)")
            plot_ax.set_ylabel("Lock-In Amp Voltage")
            plot_ax.set_title("Live Data")
            plot_ax.grid(True)
            plot_fig.canvas.draw()

        # Resize behavior
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

    # === original callbacks, scoped to this frame ===
    def browse_save_location(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if filepath:
            self.save_location_entry.delete(0, tk.END)
            self.save_location_entry.insert(0, filepath)

    def initialize_live_plot(self):
        global plot_fig, plot_ax, plot_line
        if plot_fig is None:
            plot_fig, plot_ax = plt.subplots()
            plot_line, = plot_ax.plot([], [], 'b-')
            plot_ax.set_xlabel("Wavelength (nm)")
            plot_ax.set_ylabel("Lock-In Amp Voltage")
            plot_ax.set_title("Live Data")
            plot_ax.grid(True)
            canvas = FigureCanvasTkAgg(plot_fig, master=self)
            canvas.get_tk_widget().pack(fill="both", expand=True)
            plot_fig.tight_layout()
        else:
            plot_ax.clear()
            plot_ax.set_xlabel("Wavelength (nm)")
            plot_ax.set_ylabel("Lock-In Amp Voltage")
            plot_ax.set_title("Live Data")
            plot_ax.grid(True)
            plot_fig.canvas.draw()

    def update_live_plot(self):
        global scan_wls, scan_data, plot_line, plot_ax, plot_fig
        if plot_line:
            plot_line.set_data(scan_wls[:len(scan_data)], scan_data)
            plot_ax.relim()
            plot_ax.autoscale_view()
            plot_fig.canvas.draw()

    def start_scan(self):
        global scan_data, scan_wls, scan_stopped
        scan_stopped = False
        try:
            start_wl = float(self.start_entry.get())
            end_wl = float(self.end_entry.get())
            step_size = int(self.step_entry.get())
            save_path = self.save_location_entry.get()

            if not save_path:
                messagebox.showerror("Error", "Please select a save location.")
                return

            scan_wls = np.linspace(start_wl, end_wl, step_size + 1)
            scan_data = []

            run("goto", start_wl)
            time.sleep(5)
            run("open_shutter")

            def step_loop(index=0):
                global scan_stopped
                if scan_stopped or index >= len(scan_wls):
                    run("close_shutter")
                    if not scan_stopped:
                        np.savetxt(save_path, np.column_stack([scan_wls, scan_data]),
                                   delimiter=",", header="Wavelength,Intensity", comments='')
                    return

                wl = scan_wls[index]
                run("goto", wl)
                intensity = dm.record()
                scan_data.append(intensity)
                self.update_live_plot()
                root.after(100, lambda: step_loop(index + 1))

            root.after(0, step_loop)

        except ValueError:
            messagebox.showerror("Input Error", "Start/End wavelengths and step size must be numbers.")
        except Exception as e:
            messagebox.showerror("Unexpected Error", str(e))

    def threaded_scan(self):
        threading.Thread(target=self.start_scan, daemon=True).start()

    def stop_scan(self):
        global scan_stopped
        scan_stopped = True

    def start_scan_with_plot(self):
        self.initialize_live_plot()
        self.threaded_scan()

    def set_wavelength(self):
        set_wl = float(self.wl_entry.get())
        run("goto", set_wl)

    def open_shutter(self):
        run("open_shutter")

    def close_shutter(self):
        run("close_shutter")

    def get_wav(self):
        try:
            wavelength = run("position")
            self.current_wavelength_label.config(text=f"Current Wavelength: {wavelength}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

# =========================
# FLIM GUI (Stage + Mono + TH260)
# =========================

class FlimFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.stage = None
        self.th = None
        self.scan_stop = threading.Event()
        self.build_ui()

    def build_ui(self):
        # Left pane: config
        cfg = ttk.LabelFrame(self, text="FLIM Config", padding=10)
        cfg.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        # Helper paths
        ttk.Label(cfg, text="TH260 helper:").grid(row=0, column=0, sticky="e")
        self.th_exe = ttk.Entry(cfg, width=50); self.th_exe.grid(row=0, column=1, padx=5, pady=2)
        ttk.Label(cfg, text="Stage helper:").grid(row=1, column=0, sticky="e")
        self.st_exe = ttk.Entry(cfg, width=50); self.st_exe.grid(row=1, column=1, padx=5, pady=2)

        # Defaults (adjust these paths)
        self.th_exe.insert(0, r"C:\path\to\th260_helper.exe")
        self.st_exe.insert(0, r"C:\path\to\stage_helper.exe")

        # Stage serials
        ttk.Label(cfg, text="Stage X serial:").grid(row=2, column=0, sticky="e")
        self.serial_x = ttk.Entry(cfg); self.serial_x.grid(row=2, column=1, padx=5, pady=2)
        self.serial_x.insert(0, "29503259")
        ttk.Label(cfg, text="Stage Y serial:").grid(row=3, column=0, sticky="e")
        self.serial_y = ttk.Entry(cfg); self.serial_y.grid(row=3, column=1, padx=5, pady=2)
        self.serial_y.insert(0, "29500307")

        # Grid + wavelengths
        ttk.Label(cfg, text="Width (px):").grid(row=4, column=0, sticky="e")
        self.width_e = ttk.Entry(cfg); self.width_e.grid(row=4, column=1, padx=5, pady=2); self.width_e.insert(0, "5")
        ttk.Label(cfg, text="Height (px):").grid(row=5, column=0, sticky="e")
        self.height_e = ttk.Entry(cfg); self.height_e.grid(row=5, column=1, padx=5, pady=2); self.height_e.insert(0, "5")

        ttk.Label(cfg, text="Wavelengths (nm, comma):").grid(row=6, column=0, sticky="e")
        self.wls_e = ttk.Entry(cfg, width=50); self.wls_e.grid(row=6, column=1, padx=5, pady=2)
        self.wls_e.insert(0, "500,510,520")

        # Timing
        ttk.Label(cfg, text="Tacq (ms):").grid(row=7, column=0, sticky="e")
        self.tacq_e = ttk.Entry(cfg); self.tacq_e.grid(row=7, column=1, padx=5, pady=2); self.tacq_e.insert(0, "1000")
        ttk.Label(cfg, text="Stage settle (ms):").grid(row=8, column=0, sticky="e")
        self.stage_settle_e = ttk.Entry(cfg); self.stage_settle_e.grid(row=8, column=1, padx=5, pady=2); self.stage_settle_e.insert(0, "100")
        ttk.Label(cfg, text="Mono settle (ms):").grid(row=9, column=0, sticky="e")
        self.mono_settle_e = ttk.Entry(cfg); self.mono_settle_e.grid(row=9, column=1, padx=5, pady=2); self.mono_settle_e.insert(0, "800")

        # Save dir
        ttk.Label(cfg, text="Output folder:").grid(row=10, column=0, sticky="e")
        self.out_e = ttk.Entry(cfg, width=50); self.out_e.grid(row=10, column=1, padx=5, pady=2)
        ttk.Button(cfg, text="Browse...", command=self.pick_outdir).grid(row=10, column=2, padx=5)

        # Actions
        btns = ttk.Frame(cfg)
        btns.grid(row=11, column=0, columnspan=3, pady=10)
        ttk.Button(btns, text="Connect Helpers", command=self.connect_helpers).grid(row=0, column=0, padx=5)
        ttk.Button(btns, text="Disconnect", command=self.disconnect_helpers).grid(row=0, column=1, padx=5)
        ttk.Button(btns, text="Start FLIM Scan", command=self.start_scan).grid(row=0, column=2, padx=5)
        ttk.Button(btns, text="Stop", command=self.stop_scan).grid(row=0, column=3, padx=5)

        # Status
        self.status = ttk.Label(self, text="Status: idle")
        self.status.grid(row=1, column=0, padx=10, sticky="w")

        # Resize
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

    def pick_outdir(self):
        d = filedialog.askdirectory()
        if d:
            self.out_e.delete(0, tk.END)
            self.out_e.insert(0, d)

    def connect_helpers(self):
        try:
            if self.th is None:
                self.th = TH260Client(self.th_exe.get())
                self.th.init(binning=1, offset_ps=0, sync_div=1, sync_offset_ps=25000)
                res_ps, ch, hlen = self.th.info()
                self.status.config(text=f"TH260 ready: {ch} ch, {hlen} bins, {res_ps:.1f} ps/bin")
            if self.stage is None:
                self.stage = StageClient(self.st_exe.get())
                self.stage.open(self.serial_x.get(), self.serial_y.get(), 750)
                self.status.config(text=self.status.cget("text") + " | Stage ready")
        except Exception as e:
            messagebox.showerror("Connect error", str(e))

    def disconnect_helpers(self):
        try:
            if self.stage: self.stage.close()
        except Exception:
            pass
        finally:
            self.stage = None
        try:
            if self.th: self.th.close()
        except Exception:
            pass
        finally:
            self.th = None
        self.status.config(text="Status: disconnected")

    def start_scan(self):
        if self.th is None or self.stage is None:
            messagebox.showerror("Not connected", "Connect helpers first.")
            return
        outdir = self.out_e.get().strip()
        if not outdir:
            messagebox.showerror("Output", "Pick an output folder.")
            return
        os.makedirs(outdir, exist_ok=True)
        self.scan_stop.clear()
        t = threading.Thread(target=self._scan_thread, args=(outdir,), daemon=True)
        t.start()
        self.status.config(text="Status: scanning...")

    def stop_scan(self):
        self.scan_stop.set()
        self.status.config(text="Status: stopping...")

    def _scan_thread(self, outdir):
        try:
            width  = int(self.width_e.get())
            height = int(self.height_e.get())
            wls = [float(x) for x in self.wls_e.get().replace(";", ",").split(",") if x.strip()]
            tacq_ms = int(self.tacq_e.get())
            st_settle = float(self.stage_settle_e.get())/1000.0
            mono_settle = float(self.mono_settle_e.get())/1000.0

            # Query TH260 info once for metadata
            res_ps, ch, hlen = self.th.info()

            for iy in range(height):
                for ix in range(width):
                    if self.scan_stop.is_set(): raise KeyboardInterrupt()

                    # 1) move stage
                    self.stage.move_ix(ix, iy, width, height)
                    time.sleep(st_settle)

                    for nm in wls:
                        if self.scan_stop.is_set(): raise KeyboardInterrupt()

                        # 2) move spectrograph
                        run("goto", nm)
                        time.sleep(mono_settle)  # or poll 'position' if you prefer

                        # 3) TH260 acquire
                        counts = self.th.acquire(tacq_ms=tacq_ms)  # shape (ch, hlen), uint32

                        # 4) save one NPZ per (y,x,λ)
                        fname = os.path.join(outdir, f"y{iy:03d}_x{ix:03d}_nm{nm:.1f}.npz")
                        np.savez_compressed(
                            fname,
                            counts=counts,
                            res_ps=res_ps,
                            tacq_ms=tacq_ms,
                            wavelength_nm=nm,
                            pixel=(iy, ix),
                        )
                    # update status line
                    self._set_status(f"Scanning... row {iy+1}/{height}, col {ix+1}/{width}")

            self._set_status("Done.")
        except KeyboardInterrupt:
            self._set_status("Stopped.")
        except Exception as e:
            self._set_status(f"Error: {e}")
            messagebox.showerror("FLIM scan error", str(e))

    def _set_status(self, s):
        # marshal to UI thread
        self.after(0, lambda: self.status.config(text=s))

# =========================
# App shell with Mode menu
# =========================

root = tk.Tk()
root.title("HyperSpectral")
root.geometry("1200x700")
root.resizable(True, True)

# Determine icon path (works for both dev and bundled exe)
if getattr(sys, 'frozen', False):
    icon_path = os.path.join(sys._MEIPASS, "icon.ico")
else:
    icon_path = "icon.ico"
if os.path.exists(icon_path):
    try:
        root.iconbitmap(icon_path)
    except Exception:
        pass

container = ttk.Frame(root)
container.pack(fill="both", expand=True)

# Two pages
spectro_page = SpectrographFrame(container)
flim_page = FlimFrame(container)

for page in (spectro_page, flim_page):
    page.grid(row=0, column=0, sticky="nsew")

# Show spectrograph first
current_page = [spectro_page]
spectro_page.tkraise()

def show_page(which):
    current_page[0] = spectro_page if which == "spectro" else flim_page
    current_page[0].tkraise()

# Menubar
menubar = tk.Menu(root)
mode_menu = tk.Menu(menubar, tearoff=0)
mode_menu.add_command(label="Spectrograph Only", command=lambda: show_page("spectro"))
mode_menu.add_command(label="FLIM (Stage + Mono + TH260)", command=lambda: show_page("flim"))
menubar.add_cascade(label="Mode", menu=mode_menu)
root.config(menu=menubar)

root.mainloop()
