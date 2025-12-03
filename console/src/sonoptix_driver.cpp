#include <opencv2/opencv.hpp>
#include <curl/curl.h>
#include <iostream>
#include <fstream>
#include <chrono>
#include <thread>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <filesystem>
#include <csignal>

#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #include <windows.h>
    #pragma comment(lib, "ws2_32.lib")
#else
    #include <sys/socket.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #define SOCKET int
    #define INVALID_SOCKET -1
    #define SOCKET_ERROR -1
    #define closesocket close
    #define Sleep(x) usleep((x)*1000)
#endif

using namespace cv;
using namespace std;
namespace fs = std::filesystem;

const int PREVIEW_PORT = 5002;
//const string PREVIEW_IP = "192.168.2.1";
const string PREVIEW_IP = "127.0.0.1";
const int RECORD_EVERY_N_FRAMES = 1; // Set to 2 or 3 if saving is too slow

bool debug_mode = false;
string session_path = ".";
string folder_images;
string folder_raw;
time_t t = time(NULL);

SOCKET udp_socket;
struct sockaddr_in server_addr;

typedef struct {
    cv::Mat frame;
    int64_t timestamp;
} FrameItem;

queue<FrameItem> frame_queue;
mutex queue_mutex;
condition_variable queue_not_empty;
const int MAX_QUEUE_SIZE = 1000;

atomic<bool> keep_running(true);

string sonar_ip = "192.168.2.42";
string rtsp_url = "rtsp://" + sonar_ip + ":8554/raw";
string api_url = "http://" + sonar_ip + ":8000/api/v2";

void init_udp() {
    #ifdef _WIN32
        WSADATA wsaData;
        WSAStartup(MAKEWORD(2, 2), &wsaData);
    #endif
    udp_socket = socket(AF_INET, SOCK_DGRAM, 0);
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(PREVIEW_PORT);
    server_addr.sin_addr.s_addr = inet_addr(PREVIEW_IP.c_str());
}

void send_udp_preview(const cv::Mat& frame) {
    if (frame.empty()) return;
    cv::Mat preview;
    cv::resize(frame, preview, cv::Size(400, 225));
    cv::Mat send_frame = preview;
    if (preview.type() == CV_16U) {
        double min, max;
        minMaxLoc(preview, &min, &max);
        preview.convertTo(send_frame, CV_8U, 255.0/(max-min), -min*255.0/(max-min));
        applyColorMap(send_frame, send_frame, COLORMAP_JET);
    }
    std::vector<uchar> buffer;
    std::vector<int> params = {cv::IMWRITE_JPEG_QUALITY, 50};
    cv::imencode(".jpg", send_frame, buffer, params);
    if (buffer.size() < 60000) {
        sendto(udp_socket, (const char*)buffer.data(), buffer.size(), 0,
               (struct sockaddr*)&server_addr, sizeof(server_addr));
    }
}

bool init_curl_request(const string& url, const string& payload, const string& method) {
    CURL* curl = curl_easy_init();
    if (curl) {
        struct curl_slist* headers = nullptr;
        headers = curl_slist_append(headers, "Content-Type: application/json");
        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, method.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, payload.c_str());
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

        curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 2L);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 3L);

        CURLcode res = curl_easy_perform(curl);

        if (res != CURLE_OK) {
            cerr << "[Sonar Error] cURL failed: " << curl_easy_strerror(res) << endl;
        }

        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
        return (res == CURLE_OK);
    }
    return false;
}

void stop_sonar_transponder() {
    if (debug_mode) return;
    const int MAX_RETRIES = 3;
    const string url = api_url + "/transceiver/power";
    const string payload = "{\"power_state\": \"off\"}";
    for (int i = 0; i < MAX_RETRIES; i++) {
        cout << "[Sonar] Disabling Transponder (Attempt " << i + 1 << "/" << MAX_RETRIES << ")..." << endl;
        bool success = init_curl_request(url, payload, "PUT");
        if (success) return;
        if (i < MAX_RETRIES - 1) std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
    cerr << "[Sonar Error] CRITICAL: Failed to disable transponder." << endl;
}

#ifdef _WIN32
BOOL WINAPI CtrlHandler(DWORD fdwCtrlType) {
    switch (fdwCtrlType) {
    case CTRL_C_EVENT:
    case CTRL_CLOSE_EVENT:
    case CTRL_BREAK_EVENT:
        keep_running = false;
        queue_not_empty.notify_all();

        return TRUE;
    default:
        return FALSE;
    }
}
#else
void linuxSigHandler(int s){
    keep_running = false;
    queue_not_empty.notify_all();
}
#endif

void intHandler(int k) {
    keep_running = false;
    queue_not_empty.notify_all();
}

void enqueue_frame(FrameItem frame){
    unique_lock<mutex> lock(queue_mutex);
    if(frame_queue.size() >= MAX_QUEUE_SIZE) frame_queue.pop();
    frame_queue.push(frame);
    lock.unlock();
    queue_not_empty.notify_one();
}

FrameItem dequeue_frame(){
    unique_lock<mutex> lock(queue_mutex);
    while(frame_queue.empty() && keep_running){
        queue_not_empty.wait(lock);
    }
    if(frame_queue.empty()) return FrameItem();
    FrameItem item = frame_queue.front();
    frame_queue.pop();
    return item;
}

void capture_func(){
    VideoCapture cap;
    if (debug_mode) {
        #ifdef _WIN32
            cap.open(0, cv::CAP_DSHOW);
        #else
            cap.open(0);
        #endif
        cap.set(cv::CAP_PROP_FRAME_WIDTH, 1280);
        cap.set(cv::CAP_PROP_FRAME_HEIGHT, 720);
    } else {
        cout << "[Sonar] Attempting to connect to " << rtsp_url << "..." << endl;
        cap.open(rtsp_url, cv::CAP_FFMPEG);

        cap.set(cv::CAP_PROP_BUFFERSIZE, 1);
    }

    if (!cap.isOpened()){
        keep_running = false;
        return;
    }

    cap.set(cv::CAP_PROP_READ_TIMEOUT_MSEC, 1000);
    
    Mat frame;
    auto last_frame_time = std::chrono::steady_clock::now();
    int frame_cont = 0;

    while(keep_running){
        bool success = cap.read(frame);
        auto now_steady = std::chrono::steady_clock::now();

        if (!success || frame.empty()) {
             auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now_steady - last_frame_time).count();
             if (elapsed > 5) {
                 cerr << "[Sonar Error] Stream lost or frozen > 5s. Exiting." << endl;
                 keep_running = false;
                 queue_not_empty.notify_all();
                 break;
             }
             continue;
        }
        last_frame_time = now_steady;

        // Send preview every other frame to save bandwidth
        if (frame_cont % 2 == 0) send_udp_preview(frame);

        frame_cont++;

        // Only save to disk every Nth frame
        if (frame_cont % RECORD_EVERY_N_FRAMES == 0) {
            Mat gray_frame;
            if (frame.channels() == 3) cvtColor(frame, gray_frame, COLOR_BGR2GRAY);
            else gray_frame = frame.clone();

            auto now = chrono::system_clock::now();
            int64_t timestamp = chrono::duration_cast<chrono::milliseconds>(now.time_since_epoch()).count();

            FrameItem frame_items;
            frame_items.frame = gray_frame;
            frame_items.timestamp = timestamp;

            enqueue_frame(frame_items);
        }
    }
    if(cap.isOpened()) cap.release();
}

void save_func(){
    // FOLDER STRUCTURE: .../session_X/sonar/images
    stringstream ss_img, ss_raw;
    ss_img << session_path << "/sonar/images";
    ss_raw << session_path << "/sonar/raw";

    folder_images = ss_img.str();
    folder_raw = ss_raw.str();

    try {
        fs::create_directories(folder_images);
        fs::create_directories(folder_raw);
    } catch (...) {}

    int i = 0;
    while (keep_running || !frame_queue.empty()) {
        if (!keep_running && frame_queue.empty()) break;
        FrameItem item = dequeue_frame();
        if (item.frame.empty()) continue;

        stringstream filepath;
        filepath << folder_images << "/image" << i << ".jpg";
        try {
            cv::imwrite(filepath.str(), item.frame);
            stringstream ts_path;
            ts_path << folder_raw << "/frame" << i << ".txt";
            ofstream file_timestamp(ts_path.str());
            if (file_timestamp.is_open()) {
                file_timestamp << "image" << i << " " << fixed << item.timestamp << endl;
                file_timestamp << item.frame << "\n" << endl;
            }
        } catch (...) {}
        i++;
    }
}

void watchdog_func() {
    char c;
    while (std::cin.get(c)) {}
    if (keep_running) {
        keep_running = false;
        stop_sonar_transponder();
        queue_not_empty.notify_all();
    }
}

int main(int argc, char** argv) {
    curl_global_init(CURL_GLOBAL_ALL);
    init_udp();

    for(int i = 1; i < argc; ++i) {
        string arg = argv[i];
        if (arg == "--debug") {
            debug_mode = true;
            cout << "DEBUG MODE ENABLED." << endl;
        } else if (arg == "--out" && i + 1 < argc) {
            session_path = argv[i+1];
            cout << "Output Path Set: " << session_path << endl;
            i++;
        }
    }

    if (!debug_mode) {
        if (!init_curl_request(api_url + "/datastream", "{\"stream_type\": \"rtsp\"}", "PUT")) {
            cerr << "[Sonar Error] Failed to set RTSP stream mode." << endl;
        }
        if (!init_curl_request(api_url + "/transceiver", "{\"power_state\": \"on\", \"range\": 3.0}", "PUT")) {
            cerr << "[Sonar Error] Failed to enable transceiver." << endl;
        }
    }

    #ifdef _WIN32
        if (!SetConsoleCtrlHandler(CtrlHandler, TRUE)) {
            signal(SIGINT, intHandler);
        }
    #else
        struct sigaction sigIntHandler;
        sigIntHandler.sa_handler = linuxSigHandler;
        sigemptyset(&sigIntHandler.sa_mask);
        sigIntHandler.sa_flags = 0;
        sigaction(SIGINT, &sigIntHandler, NULL);
    #endif

    cout << "Starting Sonar Capture..." << endl;
    std::thread t_watchdog(watchdog_func);
    t_watchdog.detach();

    thread t_capture(capture_func);
    thread t_save(save_func);

    if(t_capture.joinable()) t_capture.join();
    if(t_save.joinable()) t_save.join();

    stop_sonar_transponder();
    closesocket(udp_socket);
    #ifdef _WIN32
        WSACleanup();
    #endif
    curl_global_cleanup();
    cout << "Finished." << endl;
    #ifdef _WIN32
        ExitProcess(0);
    #else
        _exit(0);
    #endif
    return 0;
}