import subprocess, threading, queue, base64, numpy as np
class THClient:
    def __init__(self, exe):
        self.p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1)
        if not self._read().startswith("OK"): raise RuntimeError("th260 not ready")
    def _read(self, to=10.0):
        q=queue.Queue()
        threading.Thread(target=lambda:q.put(self.p.stdout.readline()), daemon=True).start()
        line = q.get(timeout=to)
        if not line: raise RuntimeError("th260 closed")
        return line.strip()
    def _send(self, s, to=10.0):
        self.p.stdin.write(s+"\n"); self.p.stdin.flush()
        r=self._read(to); 
        if not r.startswith("OK"): raise RuntimeError(r); 
        return r
    def init(self, binning=1, offset_ps=0, sync_div=1, sync_offset_ps=25000):
        self._send(f"init {binning} {offset_ps} {sync_div} {sync_offset_ps}", to=20.0)
    def info(self):
        r=self._send("info"); parts=dict(kv.split("=") for kv in r[3:].split())
        return float(parts["RES"]), int(parts["CH"]), int(parts["LEN"])
    def acquire(self, tacq_ms=1000):
        r=self._send(f"acquire {tacq_ms}", to=max(10.0, tacq_ms/1000+5))
        meta=dict(kv.split("=") for kv in r[3:].split()[1:])
        ch,ln,nb = int(meta["CH"]), int(meta["LEN"]), int(meta["BYTES"])
        b64 = self._read()
        raw = base64.b64decode(b64)
        arr = np.frombuffer(raw, dtype=np.uint32)
        return arr.reshape(ch, ln)
    def close(self):
        try: self._send("exit")
        finally: self.p.terminate()
