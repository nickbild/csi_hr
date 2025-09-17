# Measuring Heart Rate Using Wi-Fi

An interesting [study](https://www.hackster.io/news/i-heart-wi-fi-f3f726a38a1f) recently demonstrated how a person's heart rate can be noninvasively monitored using Wi-Fi signals. It has been getting a lot of attention in the press, so I suspect a lot of people would like to try it out. But the paper is behind a paywall, and even if you do get your hands on it, it is difficult for most people to understand (let alone reproduce) the researchers' methods.

So I  decided to take a crack at it. I got a copy of the paper and spent some time digging in and coding up a solution that more or less reproduces the work. Some details are not fully spelled out in the paper, and the team has not released either their code or data, so I cannot guarantee that my method matches it 100%. But while it may not be identical, it is at least quite close, and more importantly, it works. And I suspect most people are more interested in playing with a system that works than they are perfectly reproducing the Pulse-Fi methods to a T.

**Important Note:** *This system is not to be used as a medical device. It could provide false measurements, so it is only for educational use.*

## How It Works

### An overview of Pulse-Fi

| ![](https://raw.githubusercontent.com/nickbild/csi_hr/refs/heads/main/media/pf_architecture.png) |
| ------------------------------------------------------------------------------------------------ |
| *An overview of the Pulse-Fi approach (📷: P. Kocheta et al.)* |

To measure heart rate without contact, a person must be positioned between two ESP32 microcontrollers. One of the devices transmits a steady stream of Channel State Information (CSI) packets, while the other receives the packets. The CSI packets provide detailed information that describes how the signal propagates from the transmitter to the receiver. Anything that interrupts the signal, like the movements of a person, alters the signal in measurable ways. This fact has been leveraged for applications like activity recognition in the past.

Heart beats also involve motion, although it is very subtle compared to what is seen in the types of activities, like walking, that activity recognition systems typically target. So to focus in on heart beats, the researchers came up with a multi-step data processing pipeline that looks like this:

| CSI Data Processing  |
|-------|
| Convert raw CSI data to amplitudes |
| Stationary noise removal |
| Pulse extraction |
| Pulse shaping |
| Data segmentation and normalization |

This processed data is then fed into a multi-layer LSTM network that predicts heart rate.

| ![](https://raw.githubusercontent.com/nickbild/csi_hr/refs/heads/main/media/pf_lstm.png) |
| ------------------------------------------------------------------------------------------------ |
| *The Pulse-Fi LSTM architecture (📷: P. Kocheta et al.)* |

### My implementation

#### Predicting heart rate

I have an Adafruit HUZZAH32 and an ESP32-DevKitC v4, both with an ESP32-WROOM-32E microcontroller. They are placed several feet apart, and the measurement area is between them. One was flashed with the [Espressif csi_send code](https://github.com/espressif/esp-csi/blob/master/examples/get-started/csi_send), and the other with the [Espressif csi_recv code](https://github.com/espressif/esp-csi/blob/master/examples/get-started/csi_recv). The source code was compiled and flashed to the devices using the [IDF docker image](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-guides/tools/idf-docker-image.html), e.g.:

```bash
git clone https://github.com/espressif/esp-csi.git
docker pull espressif/idf

# Build csi_send
docker run --rm -v $PWD:~/project -w /project -u $UID -e HOME=/tmp -it espressif/idf
cd esp-csi/examples/get-started/csi_send
idf.py set-target esp32
idf.py flash -b 921600 -p /dev/ttyUSB0
exit

# Flash csi_send
docker run --rm -v $PWD:~/csi_hr/esp-csi/examples/get-started/csi_send/project -w /project espressif/idf:latest idf.py --port /dev/ttyUSB0 flash

# Build csi_recv
docker run --rm -v $PWD:~/project -w /project -u $UID -e HOME=/tmp -it espressif/idf
cd esp-csi/examples/get-started/csi_recv
idf.py set-target esp32
idf.py flash -b 921600 -p /dev/ttyUSB0
exit

# Flash csi_recv
docker run --rm -v $PWD:~/csi_hr/esp-csi/examples/get-started/csi_recv/project -w /project espressif/idf:latest idf.py --port /dev/ttyUSB0 flash
```

After flashing, the receiving device is connected to a computer via USB so that CSI information can be collected via a serial connection. I very significantly altered Espressif's [csi_data_read_parse.py](https://github.com/espressif/esp-csi/blob/master/examples/get-started/tools/csi_data_read_parse.py) script. My new version is [read_and_process_csi.py](https://github.com/nickbild/csi_hr/blob/main/read_and_process_csi.py), and it eliminates the graphical interface, implements the five Pulse-Fi CSI data processing steps, then forwards the processed data into a trained LSTM model with the same architecture as the one in the paper to predict heart rate. It can be launched with:

```bash
python read_and_process_csi.py -p /dev/ttyUSB0
```

#### Training the machine learning model

read_and_process_csi.py can also be put into a mode where it collects CSI data and writes it to a text file (`COLLECT_TRAINING_DATA = True`), rather than making heart rate predictions. This is paired with heart rate data collected using a generic dev board with a MAX30102 pulse oximetry and heart-rate monitor module (this is *only* needed to collect training data). This data is then used in my [training script](https://github.com/nickbild/csi_hr/blob/main/train.py) that builds an LSTM model in TensorFlow with the following architecture:

```python
main_input = keras.Input(shape=(100, 192), name='main_input')
layers = keras.layers.LSTM(64, return_sequences=True, name='lstm_1')(main_input)
layers = keras.layers.Dropout(0.2, name='dropout_1')(layers)
layers = keras.layers.LSTM(32, name='lstm_2')(layers)
layers = keras.layers.Dropout(0.2, name='dropout_2')(layers)
layers = keras.layers.Dense(16, activation='relu', name='dense_1')(layers)
hr_output = keras.layers.Dense(1, name='hr_output')(layers)
```

The model ingests 100 sequential CSI packets at a time in a sliding window. The average heart rate over that window is the value it is trained to predict.

## Bill of Materials

- 1 x Adafruit HUZZAH32 (ESP32-WROOM-32E)
- 1 x ESP32-DevKitC v4 (ESP32-WROOM-32E)
- 1 x Generic dev board with MAX30102 pulse oximetry and heart-rate monitor module

## About the Author

[Nick A. Bild, MS](https://nickbild79.firebaseapp.com/#!/)
