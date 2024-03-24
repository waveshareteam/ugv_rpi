// Create a new RTCPeerConnection instance
let pc = new RTCPeerConnection();

// Function to send an offer request to the server
async function createOffer() {
    console.log("Sending offer request");

    // Fetch the offer from the server
    const offerResponse = await fetch("/offer", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            sdp: "",
            type: "offer",
        }),
    });

    // Parse the offer response
    const offer = await offerResponse.json();
    console.log("Received offer response:", offer);

    // Set the remote description based on the received offer
    await pc.setRemoteDescription(new RTCSessionDescription(offer));

    // Create an answer and set it as the local description
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
}

// Trigger the process by creating and sending an offer
createOffer();
