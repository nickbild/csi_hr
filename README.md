# Measuring Heart Rate Using Wi-Fi

An interesting [study](https://www.hackster.io/news/i-heart-wi-fi-f3f726a38a1f) recently demonstrated how a person's heart rate can be noninvasively monitored using Wi-Fi signals. It has been getting a lot of attention in the press, so I suspect a lot of people would like to try it out. But the paper is behind a paywall, and even if you do get your hands on it, it is difficult for most people to understand (let alone reproduce) the researchers' methods.

So I  decided to take a crack at it. I got a copy of the paper and spent some time digging in and coding up a solution that more or less reproduces the work. Some details are not fully spelled out in the paper, and the team has not released either their code or data, so I cannot guarantee that my method matches it 100%. But while it may not be identical, it is at least quite close, and more importantly, it works. And I suspect most people are more interested in playing with a system that works than they are perfectly reproducing the Pulse-Fi methods to a T.

**Important Note:** This system is not to be used as a medical device. It could provide false measurements, so it is only for educational use.

## How It Works

### An overview of Pulse-Fi

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

### My implementation

## Bill of Materials

- 1 x Adafruit HUZZAH32 (ESP32-WROOM-32E)
- 1 x ESP32-DevKitC v4 (ESP32-WROOM-32E)
- 1 x Generic dev board with MAX30102 pulse oximetry and heart-rate monitor module

## About the Author

[Nick A. Bild, MS](https://nickbild79.firebaseapp.com/#!/)
