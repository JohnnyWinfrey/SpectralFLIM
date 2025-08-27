import niscope
import numpy as np

def record():
    with niscope.Session("Dev1") as session:
        session.channels[1].configure_vertical(range=40.0, coupling=niscope.VerticalCoupling.DC)

        session.configure_horizontal_timing(
            min_sample_rate=50000000,
            min_num_pts=5000000,
            ref_position=50.0,  # Might comment later. This is a percentage.
            num_records=1,      # This gets used later in session initiate. Might make this global.
            enforce_realtime=True
            )
        
        with session.initiate():
            waveforms = session.channels[1].fetch()  # Really only concerned with channel 1. This was [0,1]
        #for wfm in waveforms:
        #    print('Channel {}, record {} samples acquired: {:,}\n'.format(wfm.channel, wfm.record, len(wfm.samples)))

        wfm = waveforms[0]

        data_store = []
        for i in range(len(wfm.samples)):
            data_store.append(wfm.samples[i])

        data_point = np.average(data_store)
        print(data_point)

        return data_point

