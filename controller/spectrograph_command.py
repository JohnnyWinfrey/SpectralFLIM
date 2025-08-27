import sys
from newport_spectrograph import NewportUSB

try:
    spec = NewportUSB()
    command = sys.argv[1]

    if command == "get_position":
        print("Current position:", spec.position)
    elif command == "goto":
        wavelength = float(sys.argv[2])
        spec.goto(wavelength)
        print("Moved to:", wavelength)
    elif command == "close_shutter":
        spec.close_shutter()
    elif command == "open_shutter":
        spec.open_shutter()
    elif command == "position":
        print(spec.position)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

except Exception as e:
    import traceback
    print("Exception occurred:", file=sys.stderr)
    print(str(e), file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
