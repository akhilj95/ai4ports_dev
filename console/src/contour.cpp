#include <iostream>
#include <opencv2/opencv.hpp>

using namespace cv;
using namespace std;

int main(int argc, char** argv)
{
    // ARG 1: Input Path
    // ARG 2: Output Path
    if (argc < 3) {
        cout << "Usage: ./contour <input_image> <output_image>" << endl;
        return -1;
    }

    string input_path = argv[1];
    string output_path = argv[2];

    cv::Mat img = cv::imread(input_path);
    if(img.empty()) {
        cout << "Could not read image: " << input_path << endl;
        return -1;
    }

    cv::Mat img_gray;
    cv::cvtColor(img, img_gray, cv::COLOR_BGR2GRAY);

    // REMOVED: cv::namedWindow / imshow (GUI not allowed in headless backend)

    cv::equalizeHist(img_gray, img_gray);

    cv::Mat threshold_img;
    cv::threshold(img_gray, threshold_img, 30, 255, cv::THRESH_BINARY_INV);

    std::vector<std::vector<cv::Point>> contours;
    std::vector<cv::Vec4i> hierarchy;
    cv::findContours(threshold_img, contours, hierarchy, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE);

    // Draw on the original image
    cv::drawContours(img, contours, -1, cv::Scalar(0, 255, 0), 2);

    // Save result instead of displaying it
    bool success = cv::imwrite(output_path, img);

    if (success) {
        cout << "Saved processed image to: " << output_path << endl;
        return 0;
    } else {
        cerr << "Failed to save image to: " << output_path << endl;
        return -1;
    }
}