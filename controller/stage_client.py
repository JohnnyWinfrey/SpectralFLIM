import subprocess, threading, queue
class StageClient:
    def __init__(self, exe):
        self.p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1)
        if not self._read().startswith("OK"): raise RuntimeError("stage not ready")
    def _read(self, to=10.0):
        q=queue.Queue()
        threading.Thread(target=lambda:q.put(self.p.stdout.readline()), daemon=True).start()
        line=q.get(timeout=to)
        if not line: raise RuntimeError("stage closed")
        return line.strip()
    def _send(self, s):
        self.p.stdin.write(s+"\n"); self.p.stdin.flush()
        r=self._read(); 
        if not r.startswith("OK"): raise RuntimeError(r)
        return r
    def open(self, serial_x, serial_y, vmax_tenths=750): self._send(f"open {serial_x} {serial_y} {vmax_tenths}")
    def setdac(self, vx, vy): self._send(f"setdac {vx} {vy}")
    def move_ix(self, ix, iy, width, height): self._send(f"move_ix {ix} {iy} {width} {height}")
    def disable(self): self._send("disable")
    def close(self):
        try: self._send("exit")
        finally: self.p.terminate()
