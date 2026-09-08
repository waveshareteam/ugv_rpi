// WebRTC receiver (optional low-latency view).
// The stock aiortc /offer on the robot expects an SDP *offer* from the browser
// and answers with its own.  If the server is unreachable or errors out we
// fall back silently to the MJPEG stream that is already running, so this
// script can never break the page.

let pc = null;

async function createOffer() {
    console.log("[WebRTC] sending offer request");
    try {
        pc = new RTCPeerConnection();

        // We only want to RECEIVE audio/video from the robot.
        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.addTransceiver('audio', { direction: 'recvonly' });

        pc.ontrack = function (event) {
            console.log("[WebRTC] track received:", event.track.kind);
            const videoEl = document.getElementById('remoteVideo');
            if (videoEl) {
                if (videoEl.srcObject !== event.streams[0]) {
                    videoEl.srcObject = event.streams[0];
                }
            }
        };

        pc.onconnectionstatechange = function () {
            console.log("[WebRTC] connection state:", pc.connectionState);
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        // Wait for ICE gathering so the SDP includes candidate lines
        await new Promise((resolve) => {
            if (pc.iceGatheringState === 'complete') return resolve();
            const t = setTimeout(resolve, 1500);   // don't hang forever
            pc.onicegatheringstatechange = () => {
                if (pc.iceGatheringState === 'complete') {
                    clearTimeout(t);
                    resolve();
                }
            };
        });

        const controller = new AbortController();
        const abortT = setTimeout(() => controller.abort(), 5000); // never wait longer
        let response;
        try {
            response = await fetch("/offer", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    sdp: pc.localDescription.sdp,
                    type: pc.localDescription.type,
                }),
                signal: controller.signal,
            });
        } finally {
            clearTimeout(abortT);
        }

        if (!response.ok) {
            console.warn("[WebRTC] /offer returned", response.status, "- falling back to MJPEG");
            pc.close();
            pc = null;
            return;
        }

        const answer = await response.json();
        await pc.setRemoteDescription(new RTCSessionDescription(answer));
        console.log("[WebRTC] answer applied");
    } catch (err) {
        console.warn("[WebRTC] setup failed, using MJPEG stream instead:", err);
        if (pc) { try { pc.close(); } catch (e) {} pc = null; }
    }
}

// Only auto-start on pages that actually have a WebRTC <video> element
if (document.getElementById('remoteVideo')) {
    createOffer();
}
