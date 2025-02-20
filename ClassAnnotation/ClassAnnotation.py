import logging
import os
import csv
import shutil
from typing import Optional, List, Tuple
from DICOMLib import DICOMUtils
import SimpleITK as sitk
import sitkUtils
import vtk
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import random
import numpy as np

SUPPORTED_FORMATS = [".nrrd", ".nii", ".nii.gz", ".dcm", ".DCM"]

class ClassAnnotation(ScriptedLoadableModule):
    """Module for classifying medical images using 3D Slicer."""
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Class Annotation"
        self.parent.categories = ["Examples"]
        self.parent.dependencies = []
        self.parent.contributors = ["Lorena Romeo (UMG)"]
        self.parent.helpText = """
        This module allows loading medical images in .nrrd format, 
        displaying them in 3D Slicer, and classifying them.
        """
        self.parent.acknowledgementText = "Developed with 3D Slicer."

class ClassAnnotationWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Widget per l'interfaccia grafica del modulo."""

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = ClassAnnotationLogic()
        self.loadedPatients = []
        self.currentPatientIndex = 0
        self.classificationData = {}
        self.datasetPath = ""
        self.isHierarchical = False
        self.isFlat = False
        self.manualReviewMode = False  
        self.allPatientsClassified = False  
        self.randomPatientsList = []  
        self.currentRandomPatientIndex = 0  
        self.numCasesPerClass=5

    def setup(self) -> None:
        """Configura gli elementi dell'interfaccia grafica."""
        ScriptedLoadableModuleWidget.setup(self)

        uiPath = self.resourcePath("UI/ClassAnnotation.ui")
        if not os.path.exists(uiPath):
            slicer.util.errorDisplay(f"UI file not found: {uiPath}", windowTitle="Error")
            return

        uiWidget = slicer.util.loadUI(uiPath)
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        self.ui.loadButton.clicked.connect(self.onLoadDatasetClicked)
        self.ui.class0Button.clicked.connect(lambda: self.onClassifyImage(0))
        self.ui.class1Button.clicked.connect(lambda: self.onClassifyImage(1))
        self.ui.class2Button.clicked.connect(lambda: self.onClassifyImage(2))
        self.ui.class3Button.clicked.connect(lambda: self.onClassifyImage(3))
        self.ui.class4Button.clicked.connect(lambda: self.onClassifyImage(4))

        # Inizializza i contatori delle classi
        self.classCounters = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}  

        # Associa i QLCDNumber alle rispettive classi
        self.classLCDs = {
            0: self.ui.lcdClass0,
            1: self.ui.lcdClass1,
            2: self.ui.lcdClass2,
            3: self.ui.lcdClass3,
            4: self.ui.lcdClass4
        }

        for classLabel, count in self.classCounters.items():
            self.classLCDs[classLabel].display(count)

        self.ui.reviewButton.clicked.connect(self.onReviewPatientClicked)
        self.ui.checkBox.toggled.connect(self.onCheckToggled)
        self.ui.nextPatientButton.clicked.connect(self.onLoadNextRandomPatient)
        self.ui.casesInput.setPlaceholderText("5")  


        self.ui.classificationTable.setColumnCount(2)
        self.ui.classificationTable.setHorizontalHeaderLabels(["Patient ID", "Class"])
        self.ui.classificationTable.horizontalHeader().setStretchLastSection(True)
        self.ui.classificationTable.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)
        self.disableAllButtons(True) 


    def disableAllButtons(self, disable=True):
        """Disabilita o abilita tutti i pulsanti e interazioni dell'UI."""
        self.ui.class0Button.setEnabled(not disable)
        self.ui.class1Button.setEnabled(not disable)
        self.ui.class2Button.setEnabled(not disable)
        self.ui.class3Button.setEnabled(not disable)
        self.ui.class4Button.setEnabled(not disable)
        self.ui.reviewButton.setEnabled(not disable)
        self.ui.checkBox.setEnabled(not disable)
        self.ui.nextPatientButton.setEnabled(not disable)
        self.ui.patientDropdown.setEnabled(not disable)
        self.ui.casesInput.setEnabled(not disable)

    def onLoadDatasetClicked(self):
        """Carica il dataset, aggiorna la tabella e avvia il caricamento del primo paziente."""
        datasetPath = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), "Select Dataset Folder")
        if not datasetPath:
            slicer.util.errorDisplay("⚠️ Nessun dataset selezionato!", windowTitle="Errore")
            return

        self.datasetPath = datasetPath
        self.loadedPatients.clear()
        self.currentPatientIndex = 0
        self.classificationData.clear()
        self.clearTable()
        self.randomPatientsList = []
        self.currentRandomPatientIndex = 0

        self.isFlat = self.logic.isFlatDataset(self.datasetPath)
        self.isHierarchical = self.logic.isHierarchicalDataset(self.datasetPath)

        if self.isFlat and self.isHierarchical:
            slicer.util.errorDisplay("Errore: Il dataset contiene sia cartelle che file nella cartella principale. Usa solo un formato!", windowTitle="Errore Dataset")
            self.disableAllButtons(True)
            return

        self.classificationData = self.logic.loadExistingCSV(self.datasetPath)

        allPatientIDs = self.logic.getAllPatientIDs(self.datasetPath)
        for patientID in allPatientIDs:
            if patientID not in self.classificationData:
                self.classificationData[patientID] = None  

        self.logic.saveClassificationData(self.datasetPath, self.classificationData)
        self.updateTable()  

        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath)
        for classLabel, count in self.classCounters.items():
            self.classLCDs[classLabel].display(count)

        self.populatePatientDropdown()

        nextPatient = self.logic.getNextPatient(self.datasetPath)
        if nextPatient:
            self.currentPatientID, fileList = nextPatient
            self.loadPatientImages(nextPatient)
            self.disableAllButtons(False)  
        else:
            slicer.util.infoDisplay("✔️ Tutti i pazienti sono stati caricati! Ora possono essere classificati.", windowTitle="Dataset Caricato")
            self.disableAllButtons(False)  
        
        self.ui.casesInput.setText("5")

        self.ui.labelInputPath.setText('Input Folder Path: ' + self.datasetPath)
        outputFolder = os.path.join(datasetPath, "output")
        self.ui.labelOutputPath.setText('Output Folder Path: '+ outputFolder)


    def onCheckToggled(self, checked: bool) -> None:
        """Se il Random Check è attivo, avvia il controllo random dopo la classificazione di tutti i pazienti."""
        if checked:
            try:
                num_cases_text = self.ui.casesInput.text  # Senza le parentesi `()`
                
                # Se l'utente non ha inserito nulla, usa il valore predefinito di 5
                num_cases = int(num_cases_text) if num_cases_text.strip() else 5

                if num_cases <= 0:
                    slicer.util.errorDisplay("⚠️ Inserisci un numero valido di pazienti per classe!", windowTitle="Errore")
                    self.ui.checkBox.setChecked(False)
                    return

            except ValueError:
                slicer.util.errorDisplay("⚠️ Inserisci un numero numerico valido!", windowTitle="Errore")
                self.ui.checkBox.setChecked(False)
                return

            self.numCasesPerClass = num_cases  # Aggiorna il numero di casi per classe

            if self.allPatientsClassified:
                slicer.util.infoDisplay("Random Check in corso! Premi 'Next' per visualizzare il prossimo paziente.", windowTitle="Revisione Random")
                self.startRandomCheck()
            else:
                slicer.util.infoDisplay(
                    "Random Check attivato! Una volta classificati tutti i pazienti, partirà automaticamente.",
                    windowTitle="Info"
                )

        else:
            self.randomPatientsList = []
            self.currentRandomPatientIndex = 0
            slicer.mrmlScene.Clear(0)
            self.ui.nextPatientButton.setEnabled(False)
            
    def startRandomCheck(self):
        """Avvia il Random Check selezionando pazienti casuali per ogni classe."""
        self.randomPatientsList = []
        self.currentRandomPatientIndex = 0

        classifiedPatients = self.logic.loadExistingCSV(self.datasetPath)

        if not classifiedPatients:
            slicer.util.errorDisplay("⚠️ Nessun paziente classificato disponibile!", windowTitle="Errore")
            self.ui.checkBox.setChecked(False)
            return

        patientsByClass = {}
        for patientID, classLabel in classifiedPatients.items():
            if classLabel not in patientsByClass:
                patientsByClass[classLabel] = []
            patientsByClass[classLabel].append(patientID)

        for classLabel, patients in patientsByClass.items():
    
            selectedPatients = random.sample(patients, min(len(patients), self.numCasesPerClass))
            self.randomPatientsList.extend(selectedPatients)

        random.shuffle(self.randomPatientsList)  

        self.ui.nextPatientButton.setEnabled(True)

        if self.randomPatientsList:
            self.onLoadNextRandomPatient()
        else:
            slicer.util.errorDisplay("⚠️ Nessun paziente disponibile per la revisione!", windowTitle="Errore")
            self.ui.checkBox.setChecked(False)

    def onReviewPatientClicked(self):
        """Carica il paziente selezionato dal menu a tendina per la revisione manuale."""
        patientID = self.ui.patientDropdown.currentText

        if patientID == "-":
            slicer.util.errorDisplay("⚠️ Nessun paziente selezionato per la revisione!", windowTitle="Errore")
            return

        patientFiles = self.logic.getPatientFilesForReview(self.datasetPath, patientID, self.isHierarchical)

        if patientFiles:
            slicer.mrmlScene.Clear(0)  
            self.loadPatientImages((patientID, patientFiles))  
            self.manualReviewMode = True  
            self.disableAllButtons(False)  
        else:
            slicer.util.errorDisplay(f"⚠️ Nessuna immagine trovata per il paziente {patientID}!", windowTitle="Errore")

    def onLoadNextRandomPatient(self):
        """Carica il prossimo paziente casuale dalla lista selezionata."""
        
        if not self.randomPatientsList:
            slicer.util.errorDisplay("⚠️ Nessun paziente selezionato per Random Check!", windowTitle="Errore")
            return

        if self.currentRandomPatientIndex < len(self.randomPatientsList):
            patientID = self.randomPatientsList[self.currentRandomPatientIndex]
            patientFiles = self.logic.getPatientFilesForReview(self.datasetPath, patientID, self.isHierarchical)

            if patientFiles:
                slicer.mrmlScene.Clear(0)  
                self.loadPatientImages((patientID, patientFiles))
            else:
                slicer.util.errorDisplay(f"⚠️ Nessuna immagine trovata per il paziente {patientID}!", windowTitle="Errore")

            self.currentRandomPatientIndex += 1  

            if self.currentRandomPatientIndex >= len(self.randomPatientsList):
                slicer.util.infoDisplay("✔️ Tutti i pazienti selezionati sono stati rivisti!", windowTitle="Fine Random Check")
                self.ui.checkBox.setChecked(False)
                self.ui.nextPatientButton.setEnabled(False)  

    def loadNextPatient(self):
        """Carica il prossimo paziente disponibile nel dataset."""
        self.manualReviewMode = False  

        nextPatient = self.logic.getNextPatient(self.datasetPath)

        if nextPatient:
            patientID, fileList = nextPatient
            self.currentPatientIndex += 1  
            slicer.mrmlScene.Clear(0) 
            self.loadPatientImages((patientID, fileList))
            self.disableAllButtons(False) 
        else:
            slicer.mrmlScene.Clear(0)  
            slicer.util.infoDisplay("✔️ Tutti i pazienti sono stati classificati!", windowTitle="Fine del Dataset")
            # self.disableAllButtons(True) 

    def loadPatientImages(self, patientData):
        """Carica tutte le immagini di un paziente rispettando la gestione DICOM e altri formati."""

        patientID, fileList = patientData
        self.loadedPatients = []
        self.currentPatientID = patientID  

        dicomExtensions = (".dcm", ".DCM")
        otherExtensions = tuple(ext for ext in SUPPORTED_FORMATS if ext.lower() not in dicomExtensions)

        dicomFiles = [f for f in fileList if f.lower().endswith(dicomExtensions)]
        otherFiles = [f for f in fileList if f.lower().endswith(otherExtensions)]

        hasVolume = False
        volumeNode = None  
        segmentationFiles = []
        volumeFiles = []

        try:
   
            if dicomFiles:
                dicomDir = os.path.dirname(dicomFiles[0])  
                reader = sitk.ImageSeriesReader()
                dicomSeries = reader.GetGDCMSeriesFileNames(dicomDir)  
                reader.SetFileNames(dicomSeries)
                sitkImage = reader.Execute()  

                volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
                volumeNode.SetName(f"{patientID}_DICOM") 
                sitkUtils.PushVolumeToSlicer(sitkImage, volumeNode)

                if volumeNode:
                    self.loadedPatients.append(volumeNode)
                    hasVolume = True


            for filePath in otherFiles:
                try:
                    sitkImage = sitk.ReadImage(filePath) 
                    numpyImage = sitk.GetArrayFromImage(sitkImage).astype(np.float32)  

                    # Converto in uint8 e poi di nuovo in float32
                    numpyImage_uint8 = numpyImage.astype(np.uint8)
                    numpyImage_uint8[numpyImage_uint8 >= 120] = 120  
                    numpyImage_float32 = numpyImage_uint8.astype(np.float32)

                    if np.sum(numpyImage == numpyImage_float32) == np.prod(numpyImage.shape):
                        segmentationFiles.append(filePath)
                    else:
                        volumeFiles.append(filePath)

                except Exception as e:
                    slicer.util.errorDisplay(f"❌ Errore nella lettura di {filePath}: {str(e)}", windowTitle="Errore")


            for filePath in volumeFiles:
                try:
                    sitkImage = sitk.ReadImage(filePath)  
                    
                    volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
                    volumeNode.SetName(f"{patientID}_{os.path.basename(filePath)}") 
                    sitkUtils.PushVolumeToSlicer(sitkImage, volumeNode)

                    if volumeNode:
                        self.loadedPatients.append(volumeNode)
                        hasVolume = True  

                except Exception as e:
                    slicer.util.errorDisplay(f"❌ Errore nel caricamento del volume {filePath}: {str(e)}", windowTitle="Errore")

            existingSegmentationNode = slicer.mrmlScene.GetFirstNodeByName(f"{patientID}_Segmentation")

            if hasVolume:
                if not existingSegmentationNode:
                    segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
                    segmentationNode.SetName(f"{patientID}_Segmentation")
                    
                else:
                    segmentationNode = existingSegmentationNode

            for filePath in segmentationFiles:
                try:
                    sitkImage = sitk.ReadImage(filePath)  
                    sitkLabelMap = sitk.Cast(sitkImage, sitk.sitkUInt8)

                    if hasVolume:
               
                        labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                        sitkUtils.PushVolumeToSlicer(sitkLabelMap, labelmapVolumeNode)  

                        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapVolumeNode, segmentationNode)
                        slicer.mrmlScene.RemoveNode(labelmapVolumeNode)  
                        self.loadedPatients.append(segmentationNode)

                    else:
           
                        labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                        labelmapVolumeNode.SetName(f"{patientID}_LabelMap")
                        sitkUtils.PushVolumeToSlicer(sitkLabelMap, labelmapVolumeNode)
                        self.loadedPatients.append(labelmapVolumeNode)

                except Exception as e:
                    slicer.util.errorDisplay(f"❌ Errore nel caricamento della segmentazione {filePath}: {str(e)}", windowTitle="Errore")

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore generale nel caricamento del paziente {patientID}: {str(e)}", windowTitle="Errore")

        if self.loadedPatients:
            slicer.util.setSliceViewerLayers(background=self.loadedPatients[0])
            slicer.app.processEvents()
            slicer.util.resetSliceViews()
        else:
            slicer.util.errorDisplay(f"❌ Errore: nessuna immagine caricata per {patientID}", windowTitle="Errore")

    def onClassifyImage(self, classLabel):
        """Classifica il paziente corrente e aggiorna il CSV e la tabella."""

        if not self.loadedPatients:
            slicer.util.errorDisplay("❌ Nessun paziente caricato!", windowTitle="Errore")
            return

        if not self.currentPatientID:
            slicer.util.errorDisplay("❌ Errore: impossibile determinare il paziente!", windowTitle="Errore")
            return  

        classifiedPatients = self.logic.loadExistingCSV(self.datasetPath)
        if self.currentPatientID in classifiedPatients and classifiedPatients[self.currentPatientID] is not None and not self.manualReviewMode:
            slicer.util.errorDisplay("⚠️ Questo paziente è già stato classificato!", windowTitle="Errore")
            return  

        self.classificationData[self.currentPatientID] = classLabel
        self.logic.saveClassificationData(self.datasetPath, self.classificationData)

        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath)
        for classLabel, count in self.classCounters.items():
            self.classLCDs[classLabel].display(count)  

        self.updateTable()
        self.populatePatientDropdown()

        if None not in self.classificationData.values():
            self.allPatientsClassified = True  

            if self.ui.checkBox.isChecked():  
                slicer.util.infoDisplay(
                    "Inizio della revisione casuale. Premi 'Next' per visualizzare il prossimo paziente.",
                    windowTitle="Revisione Random"
                )
                self.startRandomCheck()
                return  

        slicer.mrmlScene.Clear(0)
        self.loadNextPatient()
            
    def updateTable(self):
        """Aggiorna la tabella di classificazione con tutti gli ID dei pazienti."""
        self.clearTable()

        if not self.classificationData:
            return

        classColors = {
            0: "#FF4C4C",  # Rosso
            1: "#4CAF50",  # Verde
            2: "#FF9800",  # Arancione
            3: "#FFD700",  # Giallo
            4: "#2196F3"   # Azzurro 
        }

        for idx, (patientID, classLabel) in enumerate(self.classificationData.items()):
            self.ui.classificationTable.insertRow(idx)

            patientItem = qt.QTableWidgetItem(patientID)
            classItem = qt.QTableWidgetItem(str(classLabel) if classLabel is not None else "")

            if classLabel in classColors:
                color = qt.QColor(classColors[classLabel])
                patientItem.setBackground(color)
                classItem.setBackground(color)

            # Blocca la modifica delle celle
            patientItem.setFlags(qt.Qt.ItemIsSelectable | qt.Qt.ItemIsEnabled)
            classItem.setFlags(qt.Qt.ItemIsSelectable | qt.Qt.ItemIsEnabled)

            # Inserisci gli elementi nella tabella
            self.ui.classificationTable.setItem(idx, 0, patientItem)
            self.ui.classificationTable.setItem(idx, 1, classItem)

    def clearTable(self):
        """Svuota la tabella."""
        self.ui.classificationTable.setRowCount(0)


    def populatePatientDropdown(self):
        """Aggiorna il menu a tendina con i pazienti classificati."""
        self.ui.patientDropdown.clear()  

        self.ui.patientDropdown.addItem("-")

        patients = self.logic.loadExistingCSV(self.datasetPath) 
        classifiedPatients = {patientID: classLabel for patientID, classLabel in patients.items() if classLabel is not None}

        if not classifiedPatients:
            return  

        for patientID in sorted(classifiedPatients):
            self.ui.patientDropdown.addItem(patientID)

    def lastPatientCSV(self):
        """Restituisce l'ultimo paziente classificato dal CSV."""
        return self.logic.getLastPatientFromCSV(self.datasetPath)

class ClassAnnotationLogic(ScriptedLoadableModuleLogic):
    """Logica del modulo."""

    def isFlatDataset(self, datasetPath: str) -> bool:
        """Determina se il dataset è flat (tutti i file nella cartella principale)."""
        files = [f for f in os.listdir(datasetPath) if os.path.isfile(os.path.join(datasetPath, f)) and not f.startswith('.') and f!= 'classification_results.csv']
        return any(f.endswith(tuple(SUPPORTED_FORMATS)) for f in files)

    def isHierarchicalDataset(self, datasetPath: str) -> bool:
        """Determina se il dataset è gerarchico (ogni paziente ha una cartella)."""
        subdirs = [d for d in os.listdir(datasetPath) if os.path.isdir(os.path.join(datasetPath, d))]
        return any(any(f.endswith(tuple(SUPPORTED_FORMATS)) for f in os.listdir(os.path.join(datasetPath, d))) for d in subdirs)

    def getNextPatient(self, datasetPath: str) -> Optional[Tuple[str, List[str]]]:
        """Restituisce il prossimo paziente da classificare (quelli senza classe assegnata)."""

        self.isHierarchical = self.isHierarchicalDataset(datasetPath)
        self.isFlat = self.isFlatDataset(datasetPath)

        classifiedPatients = self.loadExistingCSV(datasetPath)

        unclassifiedPatients = {patientID: classLabel for patientID, classLabel in classifiedPatients.items() if classLabel is None}

        if not unclassifiedPatients:
            return None  

        sortedPatientIDs = sorted(unclassifiedPatients.keys())

        for patientID in sortedPatientIDs:
            if self.isHierarchical:
                patientPath = os.path.join(datasetPath, patientID)
                patientFiles = self.getPatientFiles(patientPath)
            else:
                allFiles = os.listdir(datasetPath)
                patientFiles = [os.path.join(datasetPath, f) for f in allFiles if f.startswith(patientID) and f.endswith(tuple(SUPPORTED_FORMATS))]

            if patientFiles:
                return patientID, patientFiles

        return None  

    def loadExistingPatientsFromCSV(self, csvFilePath: str) -> dict:
        """Carica i pazienti esistenti dal CSV, mantenendo anche quelli non classificati."""
        
        existingPatients = {}

        if not os.path.exists(csvFilePath):
            return existingPatients 

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)
                for row in reader:
                    if len(row) == 2:
                        patientID = row[0]
                        classLabel = row[1] if row[1].isdigit() else None  # Mantiene None se non è classificato
                        existingPatients[patientID] = int(classLabel) if classLabel is not None else None

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

        return existingPatients
        
    def getPatientFiles(self, patientPath: str) -> List[str]:
        """Restituisce la lista di file di un paziente, escludendo la cartella output."""

        if not os.path.exists(patientPath):
            return []

        files = [
            os.path.join(patientPath, f)
            for f in os.listdir(patientPath)
            if f.endswith(tuple(SUPPORTED_FORMATS))
        ]

        return files

    def getFormattedName(self, volumeNode, isHierarchical: bool, isFlat: bool) -> Optional[str]:
        """Genera il nome formattato per il paziente."""
        if volumeNode is None or volumeNode.GetStorageNode() is None:
            slicer.util.errorDisplay("Errore: il file non è stato caricato correttamente!", windowTitle="Errore")
            return None  

        filePath = volumeNode.GetStorageNode().GetFileName()
        if filePath is None:
            slicer.util.errorDisplay("Errore: il file non ha un percorso valido!", windowTitle="Errore")
            return None

        fileName = os.path.basename(filePath)
        baseName, _ = os.path.splitext(fileName)

        if baseName.endswith(".nii"):
            baseName, _ = os.path.splitext(baseName)

        if isHierarchical:
            patientID = os.path.basename(os.path.dirname(filePath))
            return f"{patientID}_{baseName}"
        else:
            return baseName.split("_")[0]

    def saveClassificationData(self, datasetPath: str, classificationData: dict):
        """Salva i dati di classificazione nel CSV e organizza i file in cartelle di output."""

        outputFolder = os.path.join(datasetPath, "output")
        if not os.path.exists(outputFolder):
            os.makedirs(outputFolder)

        csvFilePath = os.path.join(outputFolder, "classification_results.csv")

        try:
            existingPatients = self.loadExistingPatientsFromCSV(csvFilePath)

            for patientID, classLabel in classificationData.items():
                existingPatients[patientID] = classLabel

            with open(csvFilePath, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Patient ID", "Class"])
                for patientID, classLabel in sorted(existingPatients.items()):  
                    writer.writerow([patientID, classLabel if classLabel is not None else ""])

            isHierarchical = self.isHierarchicalDataset(datasetPath)

            for patientID, classLabel in existingPatients.items():
                if classLabel is not None:
                    classFolder = os.path.join(outputFolder, f"class{classLabel}")
                    if not os.path.exists(classFolder):
                        os.makedirs(classFolder)

                    self.movePatientIfReclassified(outputFolder, patientID, classLabel)

                    patientFolder = os.path.join(classFolder, patientID)
                    if not os.path.exists(patientFolder):
                        os.makedirs(patientFolder)

                    originalFilePaths = self.findOriginalFile(datasetPath, patientID, isHierarchical)
                    for originalFilePath in originalFilePaths:
                        if originalFilePath:
                            fileName = os.path.basename(originalFilePath)
                            destPath = os.path.join(patientFolder, fileName)
                            shutil.copy2(originalFilePath, destPath)

            
        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nel salvataggio del CSV: {str(e)}", windowTitle="Errore")

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nel salvataggio del CSV: {str(e)}", windowTitle="Errore")

    def findOriginalFile(self, datasetPath: str, patientID: str, isHierarchical: bool) -> List[str]:
        """Trova tutti i file originali corrispondenti al paziente, gestendo sia dataset gerarchici che flat."""
        originalFiles = []

        for root, _, files in os.walk(datasetPath):
            if "output" in root:
                continue  

            for file in files:
                baseName, _ = os.path.splitext(file)

                if isHierarchical:
                    if os.path.basename(root) == patientID:
                        originalFiles.append(os.path.join(root, file))
      
                else:
                    if baseName.startswith(patientID):
                        originalFiles.append(os.path.join(root, file))

        return originalFiles


    def movePatientIfReclassified(self, outputFolder: str, patientID: str, newClass: str):
        """Sposta la cartella del paziente nella nuova classe se il paziente è stato riclassificato."""

        for classFolder in os.listdir(outputFolder):
            currentClassPath = os.path.join(outputFolder, classFolder)

            if os.path.isdir(currentClassPath):
                patientFolderPath = os.path.join(currentClassPath, patientID)

                if os.path.exists(patientFolderPath) and classFolder != f"class{newClass}":
                    newClassFolder = os.path.join(outputFolder, f"class{newClass}")
                    if not os.path.exists(newClassFolder):
                        os.makedirs(newClassFolder)

                    newPatientPath = os.path.join(newClassFolder, patientID)
                    shutil.move(patientFolderPath, newPatientPath)

                    if not os.listdir(currentClassPath):
                        shutil.rmtree(currentClassPath)

    def getLastPatientFromCSV(self, datasetPath: str) -> Optional[str]:
        """Recupera l'ultimo paziente classificato dal CSV per sapere da dove riprendere."""
        csvFilePath = os.path.join(datasetPath, "output", "classification_results.csv")
        if not os.path.exists(csvFilePath):
            return None

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  
                last_row = None
                for row in reader:
                    if len(row) == 2:
                        last_row = row[0] 
                return last_row
        except Exception as e:
            slicer.util.errorDisplay(f"Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")
            return None
        
    def getPatientFilesForReview(self, datasetPath: str, patientID: str, isHierarchical: bool) -> List[str]:
            """Trova le immagini di un paziente già classificato."""
            patientFiles = []

            if isHierarchical:
                patientPath = os.path.join(datasetPath, patientID)
                if os.path.exists(patientPath):
                    patientFiles = [os.path.join(patientPath, f) for f in os.listdir(patientPath) if f.endswith(tuple(SUPPORTED_FORMATS))]
            else:
                for file in os.listdir(datasetPath):
                    if file.startswith(patientID) and file.endswith(tuple(SUPPORTED_FORMATS)):
                        patientFiles.append(os.path.join(datasetPath, file))

            return patientFiles
    
    def loadExistingCSV(self, datasetPath: str) -> dict:
        """Carica i pazienti già classificati dal CSV e restituisce un dizionario con i loro ID e classi."""
        csvFilePath = os.path.join(datasetPath, "output", "classification_results.csv")
        classifiedPatients = {}

        if not os.path.exists(csvFilePath):
            return classifiedPatients 

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  
                for row in reader:
                    if len(row) == 2:
                        patientID = row[0]
                        classLabel = row[1] if row[1].isdigit() else None 
                        classifiedPatients[patientID] = int(classLabel) if classLabel is not None else None

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

        return classifiedPatients
    

    def countPatientsPerClassFromCSV(self, datasetPath: str):  
        """Conta il numero di pazienti per ciascuna classe leggendo dal CSV."""
        csvFilePath = os.path.join(datasetPath, "output", "classification_results.csv")
        classCounts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}  

        if not os.path.exists(csvFilePath):
            return classCounts

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  
                for row in reader:
                    if len(row) == 2 and row[1].isdigit(): 
                        classLabel = int(row[1])
                        if classLabel in classCounts:
                            classCounts[classLabel] += 1

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

        return classCounts
    
    def getAllPatientIDs(self, datasetPath: str) -> List[str]:
        """Recupera tutti gli ID dei pazienti nel dataset, anche se non classificati."""
        patientIDs = set()

        if self.isHierarchicalDataset(datasetPath):
            patientIDs = {d for d in os.listdir(datasetPath) if os.path.isdir(os.path.join(datasetPath, d)) 
                        and d.lower() != "output" and not d.startswith('.')}

        elif self.isFlatDataset(datasetPath):
            allFiles = [f for f in os.listdir(datasetPath) if os.path.isfile(os.path.join(datasetPath, f)) 
                        and f.lower() != "output" and not f.startswith('.') and f != 'classification_results.csv']
            for fileName in allFiles:
                patientID = fileName.split("_")[0]  
                patientIDs.add(patientID)

        return sorted(patientIDs)