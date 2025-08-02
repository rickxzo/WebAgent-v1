const Chatbot = {
  data() {
    return {
      userInput: '',
      rawMessages: [],
      loading: false,
      mediaRecorder: null,
      audioChunks: [],
      recording: false,
      activeTab: 'Chat',
    };
  },
  computed: {
    messages() {
        return this.rawMessages.slice(-20);
    },

  },
  methods: {

    sendMessage() {
      if (this.userInput.trim() === '') return;
      
      
      this.rawMessages.push({ from: 'user', text: this.userInput });
      this.userInput = '';

      this.rawMessages.push({ from: 'bot', text: 'thinking...', temp: true });
      
      fetch('http://127.0.0.1:5000/respond', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ messages: this.rawMessages.filter(msg => !msg.temp) })  // send data as JSON
      })
      .then(res => res.json())
      .then(data => {
        this.rawMessages = this.rawMessages.filter(msg => !msg.temp);
        this.rawMessages.push({ from: 'bot', text: data.message });
      })
      .catch(err => {
        this.rawMessages = this.rawMessages.filter(msg => !msg.temp);

        this.rawMessages.push({ from: 'bot', text: 'Oops! Something went wrong.' });
        console.error("Error:", err);
      });


    },

    toggleRecording() {
      if (this.recording) {
        this.mediaRecorder.stop();
        this.recording = false;
        if (this.silenceTimer) clearTimeout(this.silenceTimer);
        if (this.audioContext) this.audioContext.close();
      } else {
        navigator.mediaDevices.getUserMedia({ audio: true })
          .then(stream => {
            this.audioChunks = [];
            this.mediaRecorder = new MediaRecorder(stream);
            this.mediaRecorder.start();
            this.recording = true;

            this.audioContext = new AudioContext();
            const source = this.audioContext.createMediaStreamSource(stream);
            const analyser = this.audioContext.createAnalyser();
            source.connect(analyser);
            analyser.fftSize = 2048;
            const dataArray = new Uint8Array(analyser.fftSize);

            const checkSilence = () => {
              analyser.getByteTimeDomainData(dataArray);
              const rms = Math.sqrt(dataArray.reduce((sum, val) => {
                const normalized = (val - 128) / 128;
                return sum + normalized * normalized;
              }, 0) / dataArray.length);

              if (rms < 0.01) {
                // If silent, start the 1200ms countdown to stop
                if (!this.silenceTimer) {
                  this.silenceTimer = setTimeout(() => {
                    this.mediaRecorder.stop();
                    this.recording = false;
                    this.audioContext.close();
                  }, 2000);
                }
              } else {
                // If not silent, clear any pending silence timer
                if (this.silenceTimer) {
                  clearTimeout(this.silenceTimer);
                  this.silenceTimer = null;
                }
              }

              if (this.recording) {
                requestAnimationFrame(checkSilence);
              }
            };
            checkSilence();

            this.mediaRecorder.addEventListener("dataavailable", event => {
              this.audioChunks.push(event.data);
            });

            this.mediaRecorder.addEventListener("stop", () => {
              this.userInput = "loading..."

              const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
              const formData = new FormData();
              formData.append('audio', audioBlob, 'recording.webm');
              
              fetch('http://127.0.0.1:5000/voice-to-text', {
                method: 'POST',
                body: formData
              })
              .then(res => res.json())
              .then(data => {
                this.userInput = data.text || '';
                if (this.callStarted){
                  this.sendMessage();
                }
              })
              .catch(err => {
                console.error("Voice-to-text error:", err);
              });
            });
          });
      }
    }

  },
  template: `
  <div style="display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #ffffff; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">
    <div style="width: 1000px; height: 500px; border: 1px solid #e5e5e5; border-radius: 12px; padding: 20px; background-color: #ffffff; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
        <h2 style="font-family: 'Georgia', serif; font-weight: 500; font-size: 22px;">WebResearch Agent</h2>
      </div>

      <div v-if="activeTab === 'Chat'">
        <div style="height: 355px; overflow-y: auto; margin-bottom: 16px; background: #fafafa; padding: 10px; border-radius: 8px; border: 1px solid #e5e5e5;">
          <div v-for="(msg, index) in rawMessages" :key="index" :style="{ textAlign: msg.from === 'user' ? 'right' : 'left' }">
            <div :style="{
              display: 'inline-block',
              padding: '10px 14px',
              margin: '6px 0',
              maxWidth: '80%',
              borderRadius: '16px',
              fontSize: '14px',
              lineHeight: '1.4',
              background: msg.from === 'user' ? '#e8f0fe' : '#f0f0f0',
              color: '#000'
            }">
              {{ msg.text }}
            </div>
          </div>
        </div>

        <div style="display: flex; gap: 8px;">
          <input
            v-model="userInput"
            @keyup.enter="sendMessage"
            placeholder="Type your message..."
            style="flex: 1; padding: 10px 14px; border-radius: 8px; border: 1px solid #ccc; font-size: 14px;"
          />
          <button @click="toggleRecording"
            :style="{
              padding: '10px',
              borderRadius: '8px',
              border: '1px solid #ccc',
              backgroundColor: recording ? '#e6ffddff' : '#ffffffff',
              cursor: 'pointer'
            }"
            :title="recording ? 'Recording...' : 'Record Voice'"
          >
            <img src="static/images/microphone.png" alt="Logo" />
          </button>
        </div>
      </div>
    </div>
  </div>
  `
};

const app = Vue.createApp({});
app.component("chatbot",Chatbot);
app.mount('#app');