import os
import cv2
import numpy as np
from ftplib import FTP
import shutil
import random
from watchdog.events import FileSystemEventHandler
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets
import sys 
import time 
import pyqtgraph as pg
from pyqtgraph.Qt import QtGui
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

reached_max = {"focus":False,"second_dispersion":False,"third_dispersion":False}

MIRROR_FILE_PATH = r'mirror_command/mirror_change.txt'
DISPERSION_FILE_PATH = r'dazzler_command/dispersion.txt'

with open(MIRROR_FILE_PATH, 'r') as file:
    content = file.read()
mirror_values = list(map(int, content.split()))

with open(DISPERSION_FILE_PATH, 'r') as file:
    content = file.readlines()

dispersion_values = {
    0: int(content[0].split('=')[1].strip()),  # 0 is the key for 'order2'
    1: int(content[1].split('=')[1].strip())   # 1 is the key for 'order3'
}

class ImageHandler(FileSystemEventHandler):
    def __init__(self, process_images_callback):
        super().__init__()
        self.process_images_callback = process_images_callback

    def on_created(self, event):
        if not event.is_directory:
            self.process_images_callback([event.src_path])
                      
class BetatronApplication(QtWidgets.QApplication):
    def __init__(self, *args, **kwargs):
        super(BetatronApplication, self).__init__(*args, **kwargs)

        self.mean_count_per_n_images  = 0
        self.count_grad = 0
        self.n_images = 5
        self.n_images_dir_run_count = 0
        self.n_images_run_count = 0
        self.run_count = 0
        self.n_images_count_sum = 0  
        self.record_count_history = []
        self.count_history = []
        self.focus_learning_rate = 0.1
        self.second_dispersion_learning_rate = 0.1
        self.third_dispersion_learning_rate = 0.1

        self.IMG_PATH = r'C:\Users\blehe\Desktop\Betatron\images'
        self.image_files = [os.path.join(self.IMG_PATH, filename) for filename in os.listdir(self.IMG_PATH) if filename.endswith('.png') and os.path.isfile(os.path.join(self.IMG_PATH, filename))]

        self.printed_message = False
        self.initialize_image_files()

    # ------------ Plotting ------------ #

        self.third_dispersion_der_history = []
        self.second_dispersion_der_history = []
        self.focus_der_history = []
        self.total_gradient_history = []

        self.iteration_data = []
        self.der_iteration_data = []
        self.count_data = []
        
        self.count_plot_widget = pg.PlotWidget()
        self.count_plot_widget.setWindowTitle('count optimization')
        self.count_plot_widget.setLabel('left', 'count')
        self.count_plot_widget.setLabel('bottom', 'n_images iteration')
        self.count_plot_widget.showGrid(x=True, y=True)
        self.count_plot_widget.show()

        self.main_plot_window = pg.GraphicsLayoutWidget()
        self.main_plot_window.show()

        layout = self.main_plot_window.addLayout(row=0, col=0)

        self.count_plot_widget = layout.addPlot(title='count vs n_images iteration')
        self.focus_plot = layout.addPlot(title='count_focus_derivative')
        self.second_dispersion_plot = layout.addPlot(title='count_second_dispersion_derivative')
        self.third_dispersion_plot = layout.addPlot(title='count_third_dispersion_derivative')
        self.total_gradient_plot = layout.addPlot(title='total_gradient')

        subplots = [self.count_plot_widget, self.focus_plot, self.second_dispersion_plot, self.third_dispersion_plot, self.total_gradient_plot]
        for subplot in subplots:
            subplot.showGrid(x=True, y=True)

        self.plot_curve = self.count_plot_widget.plot(pen='r')
        self.focus_curve = self.focus_plot.plot(pen='r', name='focus derivative')
        self.second_dispersion_curve = self.second_dispersion_plot.plot(pen='g', name='second dispersion derivative')
        self.third_dispersion_curve = self.third_dispersion_plot.plot(pen='b', name='third dispersion derivative')
        self.total_gradient_curve = self.total_gradient_plot.plot(pen='y', name='total gradient')

        self.plot_curve.setData(self.iteration_data, self.count_history)
        self.focus_curve.setData(self.der_iteration_data, self.focus_der_history)
        self.second_dispersion_curve.setData(self.der_iteration_data, self.second_dispersion_der_history)
        self.third_dispersion_curve.setData(self.der_iteration_data, self.third_dispersion_der_history)
        self.total_gradient_curve.setData(self.der_iteration_data, self.total_gradient_history)

    # ------------ Deformable mirror ------------ #

        # init -150
        self.MIRROR_HOST = "192.168.200.3"
        self.MIRROR_USER = "Utilisateur"
        self.MIRROR_PASSWORD = "alls"    

        self.initial_focus = mirror_values[0]
        self.focus_history = []    
        self.FOCUS_LOWER_BOUND = max(self.initial_focus - 20, -200)
        self.FOCUS_UPPER_BOUND = min(self.initial_focus + 20, 200)

        self.tolerance = 100

    # ------------ Dazzler ------------ #

        self.DAZZLER_HOST = "192.168.58.7"
        self.DAZZLER_USER = "fastlite"
        self.DAZZLER_PASSWORD = "fastlite"

        # 36100 initial 
        self.initial_second_dispersion = dispersion_values[0] 
        self.second_dispersion_history = []
        self.SECOND_DISPERSION_LOWER_BOUND = max(self.initial_second_dispersion - 500, 30000)
        self.SECOND_DISPERSION_UPPER_BOUND = min(self.initial_second_dispersion + 500, 40000)

        # -27000 initial
        self.initial_third_dispersion = dispersion_values[1] 
        self.third_dispersion_history = []
        self.THIRD_DISPERSION_LOWER_BOUND = max(self.initial_third_dispersion -2000, -30000)
        self.THIRD_DISPERSION_UPPER_BOUND = min(self.initial_third_dispersion + 2000, -25000)

        self.random_direction = []

        self.image_handler = ImageHandler(self.process_images)
        self.file_observer = Observer()
        self.file_observer.schedule(self.image_handler, path=self.IMG_PATH, recursive=False)
        self.file_observer.start()

        self.random_direction = [random.choice([-1, 1]) for _ in range(4)]

    def periodic_processing(self):
        self.process_images(self.image_files)
            
    def initialize_image_files(self):
        if not self.printed_message:
            print("Waiting for images ...")
            self.printed_message = True

        new_files = [os.path.join(self.IMG_PATH, filename) for filename in os.listdir(self.IMG_PATH) if filename.endswith('.png') and os.path.isfile(os.path.join(self.IMG_PATH, filename))]

        if new_files:
            self.image_files = new_files

    def upload_files(self):
        mirror_ftp = FTP()
        dazzler_ftp = FTP()

        mirror_ftp.connect(host=self.MIRROR_HOST)
        mirror_ftp.login(user=self.MIRROR_USER, passwd=self.MIRROR_PASSWORD)

        dazzler_ftp.connect(host=self.DAZZLER_HOST)
        dazzler_ftp.login(user=self.DAZZLER_USER, passwd=self.DAZZLER_PASSWORD)

        mirror_files = [os.path.basename(MIRROR_FILE_PATH)]
        dazzler_files = [os.path.basename(DISPERSION_FILE_PATH)]

        for mirror_file_name in mirror_files:
            for dazzler_file_name in dazzler_files:
                focus_file_path = MIRROR_FILE_PATH
                dispersion_file_path = DISPERSION_FILE_PATH

                if os.path.isfile(focus_file_path) and os.path.isfile(dispersion_file_path):
                    copy_mirror_IMG_PATH = os.path.join('mirror_command', f'copy_{mirror_file_name}')
                    copy_dazzler_IMG_PATH = os.path.join('dazzler_command', f'copy_{dazzler_file_name}')

                    try:
                        os.makedirs(os.path.dirname(copy_mirror_IMG_PATH))
                        os.makedirs(os.path.dirname(copy_dazzler_IMG_PATH))
                    except OSError:
                        pass

                    shutil.copy(focus_file_path, copy_mirror_IMG_PATH)
                    shutil.copy(dispersion_file_path, copy_dazzler_IMG_PATH)

                    with open(copy_mirror_IMG_PATH, 'rb') as local_file:
                        mirror_ftp.storbinary(f'STOR {mirror_file_name}', local_file)
                        print(f"Uploaded to mirror FTP: {mirror_file_name}")

                    with open(copy_dazzler_IMG_PATH, 'rb') as local_file:
                        dazzler_ftp.storbinary(f'STOR {dazzler_file_name}', local_file)
                        print(f"Uploaded to dazzler FTP: {dazzler_file_name}")

                    os.remove(copy_mirror_IMG_PATH)
                    os.remove(copy_dazzler_IMG_PATH)

    def calc_xray_count(self, image_path):
        original_image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH)
        median_filtered_image = cv2.medianBlur(original_image, 5)
        img_mean_count = median_filtered_image.mean()

        return img_mean_count

    def initial_optimize(self):

        self.new_focus = self.focus_history[-1] + self.random_direction[0]
        self.new_second_dispersion = self.second_dispersion_history[-1] + self.random_direction[1]
        self.new_third_dispersion = self.third_dispersion_history[-1] + self.random_direction[2]
 
        self.new_focus = round(np.clip(self.new_focus, self.FOCUS_LOWER_BOUND, self.FOCUS_UPPER_BOUND))
        self.new_second_dispersion = round(np.clip(self.new_second_dispersion, self.SECOND_DISPERSION_LOWER_BOUND, self.SECOND_DISPERSION_UPPER_BOUND))
        self.new_third_dispersion = round(np.clip(self.new_third_dispersion, self.THIRD_DISPERSION_LOWER_BOUND, self.THIRD_DISPERSION_UPPER_BOUND))
 
        self.focus_history.append(self.new_focus)
        self.second_dispersion_history.append(self.new_second_dispersion)
        self.third_dispersion_history.append(self.new_third_dispersion)
 
        mirror_values[0] = (self.focus_history[-1])
        dispersion_values[0] = (self.second_dispersion_history[-1])
        dispersion_values[1] = (self.third_dispersion_history[-1])

    def calc_derivatives(self):
        self.count_focus_der = (self.count_history[-1] - self.count_history[-2]) / (self.focus_history[-1] -self.focus_history[-2])
        self.count_second_dispersion_der = (self.count_history[-1] - self.count_history[-2]) / (self.second_dispersion_history[-1] - self.second_dispersion_history[-2])
        self.count_third_dispersion_der = (self.count_history[-1] - self.count_history[-2]) / (self.third_dispersion_history[-1] - self.third_dispersion_history[-2])

        self.focus_der_history.append(self.count_focus_der)
        self.second_dispersion_der_history.append(self.count_second_dispersion_der)
        self.third_dispersion_der_history.append(self.count_third_dispersion_der)

        self.total_gradient = (self.focus_der_history[-1] + self.second_dispersion_der_history[-1] + self.third_dispersion_der_history[-1])

        self.total_gradient_history.append(self.total_gradient)
        self.der_iteration_data.append(self.n_images_dir_run_count)
        
        return {"focus":self.count_focus_der,"second_dispersion":self.count_second_dispersion_der,"third_dispersion":self.count_third_dispersion_der}

    def optimize_count(self):
        derivatives = self.calc_derivatives()

        if np.abs(self.focus_learning_rate * derivatives["focus"]) > 1:
            self.new_focus = self.focus_history[-1] + self.focus_learning_rate * self.focus_der_history[-1]
            self.new_focus = np.clip(self.new_focus, self.FOCUS_LOWER_BOUND, self.FOCUS_UPPER_BOUND)
            self.new_focus = round(self.new_focus)
            self.focus_history.append(self.new_focus)
            mirror_values[0] = self.focus_history[-1]

        if np.abs(self.second_dispersion_learning_rate * derivatives["second_dispersion"]) > 1:
            self.new_second_dispersion = self.second_dispersion_history[-1] + self.second_dispersion_learning_rate * self.second_dispersion_der_history[-1]
            self.new_second_dispersion = np.clip(self.new_second_dispersion, self.SECOND_DISPERSION_LOWER_BOUND, self.SECOND_DISPERSION_UPPER_BOUND)
            self.new_second_dispersion = round(self.new_second_dispersion)
            self.second_dispersion_history.append(self.new_second_dispersion)
            dispersion_values[0] = self.second_dispersion_history[-1]

        if np.abs(self.third_dispersion_learning_rate * derivatives["third_dispersion"]) > 1:
            self.new_third_dispersion = self.third_dispersion_history[-1] + self.third_dispersion_learning_rate * self.third_dispersion_der_history[-1]
            self.new_third_dispersion = np.clip(self.new_third_dispersion, self.THIRD_DISPERSION_LOWER_BOUND, self.THIRD_DISPERSION_UPPER_BOUND)
            self.new_third_dispersion = round(self.new_third_dispersion)
            self.third_dispersion_history.append(self.new_third_dispersion)
            dispersion_values[1] = self.third_dispersion_history[-1]
        
        if (
            np.abs(self.third_dispersion_learning_rate * derivatives["third_dispersion"]) > 1 and
            np.abs(self.second_dispersion_learning_rate * derivatives["second_dispersion"]) > 1 and
            np.abs(self.focus_learning_rate * derivatives["focus"]) > 1
        ):
            print("convergence achieved")

        if np.abs(self.count_history[-1] - self.count_history[-2]) <= self.tolerance:
            print("convergence achieved")

    def process_images(self, new_images):
        self.initialize_image_files() 
        new_images = [image_path for image_path in new_images if os.path.exists(image_path)]
        new_images.sort(key=os.path.getctime)

        for image_path in new_images:
            relative_path = os.path.relpath(image_path, self.IMG_PATH)
            img_mean_count = self.calc_xray_count(image_path)
            self.n_images_count_sum += np.sum(img_mean_count)

            self.run_count += 1

            if self.run_count % self.n_images == 0:
                self.mean_count_per_n_images = np.mean(img_mean_count)
                self.count_history.append(self.mean_count_per_n_images)
                self.n_images_run_count += 1
                self.iteration_data.append(self.n_images_run_count)

                if self.n_images_run_count == 1:
                    print('-------------')                    
                    self.focus_history.append(self.initial_focus)                       
                    self.second_dispersion_history.append(self.initial_second_dispersion)
                    self.third_dispersion_history.append(self.initial_third_dispersion)      
                    print(f"initial values are: focus {self.focus_history[-1]}, second_dispersion {self.second_dispersion_history[-1]}, third_dispersion {self.third_dispersion_history[-1]}")
                    print(f"initial directions are: focus {self.random_direction[0]}, second_dispersion {self.random_direction[1]}, third_dispersion {self.random_direction[2]}")
                    self.initial_optimize()

                else:
                    self.n_images_dir_run_count += 1
                    self.optimize_count()

                with open(MIRROR_FILE_PATH, 'w') as file:
                    file.write(' '.join(map(str, mirror_values)))

                with open(DISPERSION_FILE_PATH, 'w') as file:
                    file.write(f'order2 = {dispersion_values[0]}\n')
                    file.write(f'order3 = {dispersion_values[1]}\n')

                QtCore.QCoreApplication.processEvents()

                # print(f"{relative_path}, {self.count_history[-1]}, current values are: focus {self.focus_history[-1]}, second_dispersion {self.second_dispersion_history[-1]}, third_dispersion {self.third_dispersion_history[-1]}") 
                print(f"mean_count_per_{self.n_images}_images {self.count_history[-1]}, current values are: focus {self.focus_history[-1]}, second_dispersion {self.second_dispersion_history[-1]}, third_dispersion {self.third_dispersion_history[-1]}")
                
                # self.upload_files() # send files to second computer

                self.plot_curve.setData(self.iteration_data, self.count_history)
                self.focus_curve.setData(self.der_iteration_data, self.focus_der_history)
                self.second_dispersion_curve.setData(self.der_iteration_data, self.second_dispersion_der_history)
                self.third_dispersion_curve.setData(self.der_iteration_data, self.third_dispersion_der_history)
                self.total_gradient_curve.setData(self.der_iteration_data, self.total_gradient_history)

                print(f"count: {self.count_history}, \n focus: {self.focus_history}")
                self.n_images_count_sum = 0
                self.mean_count_per_n_images  = 0
                img_mean_count = 0  
                print('-------------')

if __name__ == "__main__":
    app = BetatronApplication([])
    win = QtWidgets.QMainWindow()
    sys.exit(app.exec_())