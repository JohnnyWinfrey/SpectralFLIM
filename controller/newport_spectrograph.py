import clr
clr.AddReference("Cornerstone")
import CornerstoneDll
import time

from typing import Dict, Union


class NewportUSB:
    """
    Python wrapper for Newport Cornerstone Devices using Cornerstone.dll via USB.
    """

    def __init__(self):
        self._mono = CornerstoneDll.Cornerstone(True)
        if not self._mono.connect():
            raise IOError("❌ Could not connect over USB")

    def __del__(self):
        try:
            self._mono.disconnect()
        except:
            pass

    @property
    def position(self) -> float:
        """Current wavelength in nanometers."""
        return self._mono.getWavelength()

    def goto(self, wavelength: float) -> float:
        """Send GOWAVE"""
        response = self._mono.getStringResponseFromCommand(f"GOWAVE {wavelength:.3f}")
        time.sleep(1)

    @property
    def grating(self) -> Dict[str, Union[int, str]]:
        """Get current grating info."""
        gnum = self._mono.getGrating()
        lines = self._mono.getGratingLines(gnum)
        label = self._mono.getGratingLabel(gnum)
        return {"number": gnum, "lines": lines, "label": label}

    def shutter(self, close: bool = True):
        # print(self._mono.getShutter())
        """Open or close shutter."""
        state = False if close else True
        self._mono.setShutter(state)

    def close_shutter(self):            # Verified
        self._mono.setShutter(False)
        print("Shutter closed.\n")

    def open_shutter(self):            # Verified
        self._mono.setShutter(True)
        print("Shutter opened.\n")

    @property
    def shuttered(self) -> bool:
        """True if shutter is closed."""
        return self._mono.getShutter() == 'C'

    @property
    def filter(self) -> int:
        """Current filter position."""
        return self._mono.getFilter()

    def set_filter(self, pos: int):
        """Set filter position."""
        self._mono.setFilter(pos)

    def slit_width(self, width: Union[int, None] = None) -> int:
        """Get or set slit width in microns."""
        if width is not None:
            self._mono.setSlitWidth(width)
        return self._mono.getSlitWidth()
    
    def query(self, msg: str) -> str:
        self._mono.disconnect()
        time.sleep(1)
        self._mono.connect()
        if not msg.endswith('?'):
            msg += '?'
        self._mono.sendCommand(msg)
        return self._mono.getResponse().strip()


