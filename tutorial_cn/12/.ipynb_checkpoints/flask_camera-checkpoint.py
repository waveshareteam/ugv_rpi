from flask import Flask, render_template, Response
from picamera2 import Picamera2
import time
import cv2

app = Flask(__name__)

def gen_frames():  # generate frame by frame from camera
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(main={"format": 'XRGB8888', "size": (640, 480)}))
    picam2.start()
    while True:
        # Capture frame-by-frame
        frame = picam2.capture_array()  # read the camera frame
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')  # concat frame one by one and show result

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    #Video streaming route. Put this in the src attribute of an img tag
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
