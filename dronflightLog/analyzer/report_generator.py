import matplotlib.pyplot as plt  
import os  
def generate_report(logs, output_path):  
    if not os.path.exists(os.path.dirname(output_path)):  
        os.makedirs(os.path.dirname(output_path))