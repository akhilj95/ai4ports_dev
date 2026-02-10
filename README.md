# AI4Ports Integrated Underwater Inspection System

This repo is an end-to-end software ecosystem designed to automate and enhance underwater structural assessments. The system streamlines the workflow from on-site robotic data capture to centralized office review. 

## 🏗️ System Architecture

The platform is divided into three primary layers to ensure low-latency field operations and robust data management:

1.  **Field Operations (The Console)**: A high-performance PyQt6 application used at the inspection site for real-time piloting and data acquisition.
2.  **Data Management (The Backend)**: A centralized Django REST API that organizes mission logs, sonar data, and video assets into a structured database.
3.  **Stakeholder Review (The Frontend)**: A browser-accessible Streamlit dashboard for searching, replaying, and analyzing mission data.

<img width="1424" height="752" alt="Workflow diagram" src="https://github.com/user-attachments/assets/a36c7729-cbf0-4faa-a925-781f5e0909f5" />

## 🚀 Technical Stack

### 1. Inspection Console (Field Layer)
The core operator interface, built with **PyQt6**, facilitates high-frame-rate multi-sensor viewing and recording.
* **Unified Visualization and Recording**: Displays live feeds from the navigation camera, high-resolution Panasonic BGH1 inspection camera, and Sonoptix Echo sonar simultaneously.
* **Hardware Interfacing**: 
    * **MAVLink**: Integration via `pymavlink` for real-time telemetry (depth, heading, yaw).
    * **UDP Streaming**: Low-latency video and sonar data transmission via dedicated C++ drivers.

### 2. Backend API (Data Layer)
A **Django 5.2** application serving as the system's backend manager.
* **Structured Database**: A PostgreSQL backend stores detailed mission metadata, sensor deployments, and media links, replacing scattered file systems.
* **REST Architecture**: Built using **Django REST Framework (DRF)** with JWT authentication for secure frontend communication.
* **Schema Management**: Includes a `django-schema-viewer` for visual database auditing.

### 3. Web Dashboard (Presentation Layer)
A lightweight **Streamlit** application designed for office-based review.
* **Mission Browser**: Allows stakeholders to search and filter inspections by location and date.
