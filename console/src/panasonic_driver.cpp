#include <iostream>
#include <fstream>
#include <sstream>
#include <opencv2/opencv.hpp>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <filesystem>
#include <atomic>
#include <csignal>
#include <chrono>

// --- CROSS-PLATFORM NETWORKING ---
#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #include <windows.h> // Needed for ExitProcess
    #pragma comment(lib, "ws2_32.lib")
#else
    #include <sys/socket.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #define SOCKET int
    #define INVALID_SOCKET -1
    #define SOCKET_ERROR -1
    #define closesocket close
#endif

using namespace cv;
using namespace std;
namespace fs = std::filesystem;

// --- CONFIGURATION ---
const int PREVIEW_PORT = 5001;
//const string PREVIEW_IP = "192.168.2.1";
const string PREVIEW_IP = "127.0.0.1";
const int RECORD_EVERY_N_FRAMES = 3;

// --- GLOBAL VARIABLES ---
bool debug_mode = false;
string session_path = ".";
string folder_images;
time_t t = time(NULL);

SOCKET udp_socket;
struct sockaddr_in server_addr;

typedef struct {
    cv::Mat frame;
    int64_t timestamp;
} FrameItem;

typedef struct {
    cv::Mat cameraMatrix;
    cv::Mat distCoeffs;
} ThreadData;

std::queue<FrameItem> frame_queue;
std::mutex queue_mutex;
std::condition_variable queue_not_empty;
const int MAX_QUEUE_SIZE = 1000;

std::atomic<bool> keep_running(true);

// --- HELPER: INIT UDP ---
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
    // Preview is smaller for fast UDP transmission
    cv::resize(frame, preview, cv::Size(400, 225));
    std::vector<uchar> buffer;
    std::vector<int> params = {cv::IMWRITE_JPEG_QUALITY, 50};
    cv::imencode(".jpg", preview, buffer, params);
    if (buffer.size() < 60000) {
        sendto(udp_socket, (const char*)buffer.data(), buffer.size(), 0,
               (struct sockaddr*)&server_addr, sizeof(server_addr));
    }
}

// --- WATCHDOG THREAD ---
// Reads from stdin. If Python closes the pipe, this triggers shutdown.
void watchdog_func() {
    char c;
    while (std::cin.get(c)) {
        // Just consuming input to detect pipe closure
    }

    if (keep_running) {
        std::cerr << "[Watchdog] Parent process disconnected. Shutting down." << std::endl;
        keep_running = false;
        queue_not_empty.notify_all();
    }
}

// --- SIGNAL HANDLER ---
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
    std::unique_lock<std::mutex> lock(queue_mutex);
    if(frame_queue.size() >= MAX_QUEUE_SIZE) frame_queue.pop();
    frame_queue.push(frame);
    lock.unlock();
    queue_not_empty.notify_one();
}

FrameItem dequeue_frame(){
    std::unique_lock<std::mutex> lock(queue_mutex);
    while(frame_queue.empty() && keep_running){
        queue_not_empty.wait(lock);
    }
    if(frame_queue.empty()) return FrameItem();
    FrameItem item = frame_queue.front();
    frame_queue.pop();
    return item;
}

void capture_thread_func(){
    VideoCapture cap;
    if (debug_mode) {
        cout << "Opening webcam..." << endl;
        #ifdef _WIN32
            cap.open(0, cv::CAP_DSHOW);
        #else
            cap.open(0);
        #endif
        cap.set(cv::CAP_PROP_FOURCC, cv::VideoWriter::fourcc('M', 'J', 'P', 'G'));
        cap.set(cv::CAP_PROP_FRAME_WIDTH, 1280);
        cap.set(cv::CAP_PROP_FRAME_HEIGHT, 720);
        cap.set(cv::CAP_PROP_FPS, 30);
    } else {
        cout << "Opening panasonic RTSP stream..." << endl;
        cap.open("rtsp://192.168.2.54:554/stream");
    }

    if (!cap.isOpened()){
        cout << "Error: Could not open video stream." << endl;
        keep_running = false;
        return;
    }

    Mat frame;
    int frame_cont = 0;

    while(keep_running){
        cap.read(frame);
        if(frame.empty()) continue;

        if (frame_cont % 2 == 0) send_udp_preview(frame);

        auto now = std::chrono::system_clock::now();
        int64_t timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();

        frame_cont++;
        if (frame_cont % RECORD_EVERY_N_FRAMES == 0){
            FrameItem frame_items;

            // --- RESTORED: RESIZE LOGIC ---
            // Resize to 850x480 before enqueueing to save space/processing time later
            cv::resize(frame, frame_items.frame, cv::Size(850, 480));
            frame_items.timestamp = timestamp;

            enqueue_frame(frame_items);
        }
    }
}

void save_thread_func(ThreadData* data){
    cv::Mat cameraMatrix = data->cameraMatrix;
    cv::Mat distCoeffs = data->distCoeffs;

    stringstream ss;
    ss << session_path << "/camera_1/images";
    folder_images = ss.str();

    try {
        fs::create_directories(folder_images);
        cout << "Created storage folder: " << folder_images << endl;
    } catch (std::exception& e) {
        cerr << "Filesystem error: " << e.what() << endl;
    }

    string timestampFile = session_path + "/camera_1/timestamps.txt";
    ofstream file_timestamp(timestampFile);

    printf("Saving images to: %s\n", folder_images.c_str());

    int i = 0;
    while (keep_running || !frame_queue.empty()){
        if (!keep_running && frame_queue.empty()) break;

        FrameItem item = dequeue_frame();
        if(item.frame.empty()) continue;

        cv::Mat undistorted;
        cv::undistort(item.frame, undistorted, cameraMatrix, distCoeffs);

        stringstream imgPath;
        imgPath << folder_images << "/image" << i << ".jpg";

        cv::imwrite(imgPath.str(), undistorted);
        file_timestamp << "image" << i << " " << fixed << item.timestamp << endl;

        i++;
    }
    file_timestamp.close();
    cout << "Save thread finished. Saved " << i << " images." << endl;
}

int main(int argc, char** argv)
{
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

    string calib_path = "config/panasonic_calib.yml";
    if (!fs::exists(calib_path)) calib_path = "../config/panasonic_calib.yml";

    cv::Mat cameraMatrix = Mat::eye(3, 3, CV_64F);
    cv::Mat distCoeffs = Mat::zeros(1, 5, CV_64F);

    cv::FileStorage fs(calib_path, cv::FileStorage::READ);
    if (fs.isOpened()) {
        fs["cameraMatrix"] >> cameraMatrix;
        fs["distCoeffs"] >> distCoeffs;
        fs.release();
    }

    ThreadData data;
    data.cameraMatrix = cameraMatrix;
    data.distCoeffs = distCoeffs;

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

    cout << "Starting Capture..." << endl;

    // --- RESTORED: WATCHDOG ---
    std::thread t_watchdog(watchdog_func);
    t_watchdog.detach();

    std::thread t_capture(capture_thread_func);
    std::thread t_save(save_thread_func, &data);

    if(t_capture.joinable()) t_capture.join();
    if(t_save.joinable()) t_save.join();

    closesocket(udp_socket);
    #ifdef _WIN32
        WSACleanup();
    #endif
    cout << "Finished." << endl;

    // --- RESTORED: AGGRESSIVE EXIT ---
    #ifdef _WIN32
        ExitProcess(0);
    #else
        _exit(0);
    #endif
    return 0;
}