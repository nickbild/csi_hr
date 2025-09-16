#!/usr/bin/env python3
# -*-coding:utf-8-*-

# Copyright 2021 Espressif Systems (Shanghai) PTE LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# WARNING: we don't check for Python build-time dependencies until
# check_environment() function below. If possible, avoid importing
# any external libraries here - put in external script, or import in
# their specific function instead.

###
# Modified by Nick Bild
# September 2025
# * Eliminate the graphical interface and calculate amplitude values for each carrier.
# * Add data preprocessing steps from Pulse-Fi paper.
# * Predict heart rate using LSTM model.
###

import sys
import csv
import json
import argparse
import numpy as np
import serial
from io import StringIO
import ast
from scipy.signal import butter, filtfilt, savgol_filter
from typing import List, Tuple, Optional, Dict, Any
import tensorflow as tf
from tensorflow import keras
import numpy as np


COLLECT_TRAINING_DATA = False

# Reduce displayed waveforms to avoid display freezes
CSI_VAID_SUBCARRIER_INTERVAL = 1
csi_vaid_subcarrier_len =0

CSI_DATA_INDEX = 200  # buffer size
CSI_DATA_COLUMNS = 490
DATA_COLUMNS_NAMES_C5C6 = ["type", "id", "mac", "rssi", "rate","noise_floor","fft_gain","agc_gain", "channel", "local_timestamp",  "sig_len", "rx_state", "len", "first_word", "data"]
DATA_COLUMNS_NAMES = ["type", "id", "mac", "rssi", "rate", "sig_mode", "mcs", "bandwidth", "smoothing", "not_sounding", "aggregation", "stbc", "fec_coding",
                      "sgi", "noise_floor", "ampdu_cnt", "channel", "secondary_channel", "local_timestamp", "ant", "sig_len", "rx_state", "len", "first_word", "data"]

csi_data_array = np.zeros(
    [CSI_DATA_INDEX, CSI_DATA_COLUMNS], dtype=np.float64)
csi_data_phase = np.zeros([CSI_DATA_INDEX, CSI_DATA_COLUMNS], dtype=np.float64)
csi_data_complex = np.zeros([CSI_DATA_INDEX, CSI_DATA_COLUMNS], dtype=np.complex64)
agc_gain_data = np.zeros([CSI_DATA_INDEX], dtype=np.float64)
fft_gain_data = np.zeros([CSI_DATA_INDEX], dtype=np.float64)
fft_gains = []
agc_gains = []


if COLLECT_TRAINING_DATA:
    train = open("training_data.txt", 'w')
else:
    model = keras.models.load_model("csi_hr.keras", safe_mode=False)

def parse_csi_amplitudes(csi_str):
    # Convert the string into a Python list of ints
    values = ast.literal_eval(csi_str)

    # Reshape into (imag, real) pairs
    complex_pairs = np.array(values).reshape(-1, 2)

    # Convert to complex numbers: real + j*imag
    csi_complex = complex_pairs[:,1] + 1j * complex_pairs[:,0]

    # Compute amplitudes
    amplitudes = np.abs(csi_complex)
    return amplitudes


def remove_dc(signal, fs, lowcut=2.0, highcut=5.0, order=3):
    """
    Remove DC and out-of-band noise using a 3rd-order Butterworth band-pass filter.
    Matches the method described in WiHear (2-5 Hz speaking band).
    
    Parameters
    ----------
    signal : array-like
        Input CSI amplitude or raw time-series signal.
    fs : float
        Sampling frequency (Hz).
    lowcut : float
        Low cutoff frequency (Hz), default = 2.0 Hz.
    highcut : float
        High cutoff frequency (Hz), default = 5.0 Hz.
    order : int
        Order of Butterworth filter, default = 3.
    
    Returns
    -------
    filtered : ndarray
        Band-pass filtered signal.
    """
    nyq = 0.5 * fs  # Nyquist frequency
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='bandpass')
    filtered = filtfilt(b, a, signal)
    return filtered


def butter_bandpass_filter(signal: np.ndarray,
                           lowcut: float,
                           highcut: float,
                           fs: float,
                           order: int = 3) -> np.ndarray:
    """
    Pulse Extraction: 3rd-order Butterworth bandpass (default order=3).
    Uses zero-phase filtering (filtfilt).
    lowcut/highcut in Hz. fs is sampling frequency (Hz).
    """
    x = np.asarray(signal, dtype=float).copy()
    if x.size == 0:
        return x
    nyq = 0.5 * fs
    if not (0 < lowcut < highcut < nyq):
        raise ValueError(f"Invalid bandpass: low={lowcut}, high={highcut}, Nyquist={nyq}")
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype="band")
    # filtfilt for zero-phase
    return filtfilt(b, a, x)


def savitzky_golay_smooth(signal: np.ndarray,
                          window_length: int = 15,
                          polyorder: int = 3) -> np.ndarray:
    """
    Pulse Shaping: Savitzky-Golay smoothing (preserve waveform shape).
    Ensures window_length is odd and less than signal length.
    If signal too short, returns original signal.
    """
    x = np.asarray(signal, dtype=float).copy()
    n = x.size
    if n == 0:
        return x
    wl = int(window_length)
    if wl % 2 == 0:
        wl += 1
    if wl < (polyorder + 2):
        raise ValueError("window_length too small for polyorder")
    if wl >= n:
        # fallback: choose the largest odd window smaller than n
        wl_candidate = n - 1
        if wl_candidate % 2 == 0:
            wl_candidate -= 1
        if wl_candidate < (polyorder + 2):
            # can't apply SG; return original
            return x
        wl = wl_candidate
    return savgol_filter(x, wl, polyorder)


def csi_data_read_parse(port: str, csv_writer, log_file_fd,callback=None):
    global fft_gains, agc_gains
    ser = serial.Serial(port=port, baudrate=921600,bytesize=8, parity='N', stopbits=1)
    count =0
    if ser.isOpen():
        print("open success")
    else:
        print("open failed")
        return
    
    frame_num = 0
    shaped_data = []
    while True:
        frame_num += 1

        strings = str(ser.readline())
        if not strings:
            break
        strings = strings.lstrip('b\'').rstrip('\\r\\n\'')
        index = strings.find('CSI_DATA')

        if index == -1:
            log_file_fd.write(strings + '\n')
            log_file_fd.flush()
            continue

        csv_reader = csv.reader(StringIO(strings))
        csi_data = next(csv_reader)
        csi_data_len = int (csi_data[-3])
        if len(csi_data) != len(DATA_COLUMNS_NAMES) and len(csi_data) != len(DATA_COLUMNS_NAMES_C5C6):
            # print("element number is not equal",len(csi_data),len(DATA_COLUMNS_NAMES) )
            # print(csi_data)
            log_file_fd.write("element number is not equal\n")
            log_file_fd.write(strings + '\n')
            log_file_fd.flush()
            continue

        try:
            csi_raw_data = json.loads(csi_data[-1])
        except json.JSONDecodeError:
            # print("data is incomplete")
            log_file_fd.write("data is incomplete\n")
            log_file_fd.write(strings + '\n')
            log_file_fd.flush()
            continue
        if csi_data_len != len(csi_raw_data):
            # print("csi_data_len is not equal",csi_data_len,len(csi_raw_data))
            log_file_fd.write("csi_data_len is not equal\n")
            log_file_fd.write(strings + '\n')
            log_file_fd.flush()
            continue

        fft_gain = int(csi_data[6])
        agc_gain = int(csi_data[7])
        
        fft_gains.append(fft_gain)
        agc_gains.append(agc_gain)

        csv_writer.writerow(csi_data)

        
        ###
        # Pulse-Fi CSI data processing steps.
        ###

        # Step 1: Amplitude conversion.
        amplitudes = parse_csi_amplitudes(csi_data[24])
        # Step 2: Stationary Noise Removal.
        dc_removed = remove_dc(amplitudes, fs=20.0)
        # Step 3: Pulse extraction.
        bandpassed = butter_bandpass_filter(dc_removed, 0.8, 2.17, 20.0, order=3)
        # Step 4: Pulse shaping.
        shaped = savitzky_golay_smooth(bandpassed, window_length=15, polyorder=3)

        if COLLECT_TRAINING_DATA:
            train.write(','.join(map(str, shaped)) + '\n')
        else:
            shaped_data.append(shaped)
            if len(shaped_data) > 100:
                # At this point, shaped_data contains the latest 100 'shaped' arrays.
                # These are ready to be fed into the LSTM.
                shaped_data = shaped_data[1:]
                # Reshape the data for input to the model.
                shaped_data_np = np.array(shaped_data, dtype=np.float32)
                shaped_data_np = shaped_data_np.reshape((1, 100, 192))  # shape: (1, 100, 192)
                # Make a heart rate prediction.
                new_prediction = model.predict(shaped_data_np, verbose=0)
                print(new_prediction[0][0])
            else:
                print("Collected {0} of 100 initial CSI samples.".format(len(shaped_data)))


        # Rotate data to the left
        # csi_data_array[:-1] = csi_data_array[1:]
        # csi_data_phase[:-1] = csi_data_phase[1:]
        csi_data_complex[:-1] = csi_data_complex[1:]
        agc_gain_data[:-1] = agc_gain_data[1:]
        fft_gain_data[:-1] = fft_gain_data[1:]
        agc_gain_data[-1] = agc_gain
        fft_gain_data[-1] = fft_gain
        
        for i in range(csi_data_len // 2):
            csi_data_complex[-1][i] = complex(csi_raw_data[i * 2 + 1],
                                            csi_raw_data[i * 2])
    ser.close()
    return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Read CSI data from serial port and display it graphically")
    parser.add_argument('-p', '--port', dest='port', action='store', required=True,
                        help="Serial port number of csv_recv device")
    parser.add_argument('-s', '--store', dest='store_file', action='store', default='./csi_data.csv',
                        help="Save the data printed by the serial port to a file")
    parser.add_argument('-l', '--log', dest="log_file", action="store", default="./csi_data_log.txt",
                        help="Save other serial data the bad CSI data to a log file")

    args = parser.parse_args()
    serial_port = args.port
    file_name = args.store_file
    log_file_name = args.log_file

    csi_data_read_parse(serial_port, csv.writer(open(file_name, 'w')), open(log_file_name, 'w'))
