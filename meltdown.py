# -*- coding: UTF-8 -*-
#!/usr/bin/env python
#
#    *                                                       
#  (  `            (       )    (                            
#  )\))(      (    )\   ( /(    )\ )         (  (            
# ((_)()\    ))\  ((_)  )\())  (()/(    (    )\))(     (     
# (_()((_)  /((_)  _   (_))/    ((_))   )\  ((_)()\    )\ )  
# |  \/  | (_))   | |  | |_     _| |   ((_) _(()((_)  _(_/(  
# | |\/| | / -_)  | |  |  _|  / _` |  / _ \ \ V  V / | ' \)) 
# |_|  |_| \___|  |_|   \__|  \__,_|  \___/  \_/\_/  |_||_| 
#
#  meltdown.py
#
#  Authors: Nicholas Rosa, Marko Ristic, Shane A. Seabrook, David Lovell, Del Lucent and Janet Newman
#
#  Website: TBD.github.com
#
#  License: XXX
#
# This software will generate automated reports from high-throughput thermofluor protein
# stability measurements.  Although originally designed to provide a report for the Buffer Screen 9
# experiment at the Collaborative Crystalisation Centre (C3), this can be extended to analyse any
# similar experiment.  Given two input xlsx files (one for fluorescence in
# each well as a function of temperature, and one describing the buffer formulation of each well in
# a standardized format) the following tasks are performed:
#
#  + data remediation including outlier removal of replicants
#  + Tm calculation and complex shape flag for curves
#  + report generation summarizing protein thermal stability as a function of buffer formulation,
#    Tm graph, formulation plots, control well checking, etc.
# 
# Additionally, given a suitable set of training data, the parameters used for outlier detection
# and Tm calculationcan be recomputed.
#
version = "1.1.0"

import math
import pandas
import Tkinter, tkFileDialog, tkMessageBox
import cStringIO
import os
import sys, traceback
import ConfigParser
import csv
import matplotlib.pyplot as plt
import numpy as np
from itertools import combinations
#reportlab needs to be installed separetly by anaconda, so a messagebox pops up alerting the user
#if there is trouble importing it
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
except:
    root = Tkinter.Tk()
    root.withdraw()
    tkMessageBox.showerror("ReportLab not found", "You must use Anaconda to install reportlab before Meltdown can be run")
    sys.exit(1)

#files from directory
import replicateHandling as rh

##====GLOBAL VARIABLES====##
#discard bad threshold, mean difference between any two of 168 normalised lysozyme curves
SIMILARITY_THRESHOLD = 1.72570084974
#lysozyme tm over all of our files: (mean,std_dev)
LYSOZYME_TM_THRESHOLD = (70.87202380952381, 0.73394932964132509)
SIGN_CHANGE_THRESH = 0.000001 # changed from 0.00001
#the different colours of the saltconcentrations, in order of appearance
COLOURS = ["Blue","DarkOrange","Green","Magenta","Cyan","Red",
            "DarkSlateGray","Olive","LightSeaGreen","DarkMagenta","Gold","Navy",
            "DarkRed","Lime","Indigo","MediumSpringGreen","DeepPink","Salmon",
            "Teal","DeepSkyBlue","DarkOliveGreen","Maroon","GoldenRod","MediumVioletRed"]

#read the settings.ini file and set the appropriate flags
RUNNING_LOCATION = os.path.dirname(os.path.realpath(__file__))
cfg = ConfigParser.ConfigParser()
cfg.readfp(open(RUNNING_LOCATION + '\\settings.ini'))
#get options
DELETE_INPUT_FILES = cfg.getboolean('Running Options', 'DeleteInputFiles')
CREATE_NORMALISED_DATA = cfg.getboolean('Extra Output', 'ProduceNormalisedData')


class DSFAnalysis:
    """
    Class used for performing the analysis of a DSF plate, methods will
    remove outliers, find mean curves, find tm's and check for monotenicity
    along with produce the final report
    """
    
    def __init__(self):
        """
        Initialises an empty list of deleted curves which is filled with unused curves
        when removing outliers from replicates
        """
        self.delCurves = []
        return
    
    def loadMeltCurves(self, fluorescenceFilepath, contentsMapFilepath):
        """
        Loads the two XLSX files and takes from them the information
        needed to start the analysis.
        
        +fluorescenceXLS is the xlsx file that stores all the melt curve data
        
        +labelsXLS is the xlsx file that stores the conditions
        """
        #populates the relevant instance variables for the analysis
        self.name = fluorescenceFilepath
        self.plate = DSFPlate(fluorescenceFilepath, contentsMapFilepath)
        self.wells = self.plate.wells
        self.originalPlate = DSFPlate(fluorescenceFilepath, contentsMapFilepath)
        self.removeOutliers()
        self.findMeanCurves()
        return
    
    def findMeanCurves(self):
        """
        Of the two plates created, we turn one (self.plate) into its own mean plate.
        Every group of retained replicates (remove outliers has already been called) is
        averaged out, and placed in a well of the appropriate mean well name.
        e.g. well group (A4, A5, A6) in a 3 replicate plate would have mean well name A2
        """
        meanWells = {}
        visited = []
        names = self.plate.names
        for well in names:
            if well not in visited:
                reps = []
                reps += self.originalPlate.repDict[well]

                i = 0
                while i < len(reps):
                    visited.append(reps[i])
                    if reps[i] in self.delCurves:
                        del reps[i]
                        i -=1    
                    i+=1
                if len(reps) > 0:
                    meanWells[well] = (meanCurve([self.wells[well].fluorescence for well in reps]),well)
                
                else:
                    meanWells[well] = (None,well)
                if well in self.plate.lysozyme:
                    self.plate.lysozyme = [well]
                if well in self.plate.noDye:
                    self.plate.noDye = [well]
                if well in self.plate.proteinAsSupplied:
                    self.plate.proteinAsSupplied = [well]
                if well in self.plate.noProtein:
                    self.plate.noProtein = [well]

                
                #creates a dictionary allowing you to find which wells created which mean well
                #e.g. 'A2': ["A4","A5","A6"]
                self.plate.meanDict[well] = self.originalPlate.repDict[well]
                
        remove = []

        for well in self.plate.names:
            if well in meanWells.keys():
                if len(self.wells) == 0:
                    return
                if well not in self.plate.names:
                    new = self.plate.names[0]
                    self.wells[well] = self.wells[new]
                if meanWells[well][0]:
                    self.wells[well].fluorescence = meanWells[well][0] 
                else:
                    self.wells[well].fluorescence = None
                self.wells[well].contents = self.originalPlate.wells[meanWells[well][1]].contents
            elif well in self.plate.names:
                del self.wells[well]
                remove.append(well)
            else:
                remove.append(well)
        for well in remove:
            self.plate.names.remove(well)
        return


    
    def removeOutliers(self):
        """
        Removes curves from analysis by adding them to self.delCurves. The removal of
        a curve is decided by it similarity to its replicates. This is further described 
        in replicateHnadling.py
        """
        #With the DSFPlate object, we can just use self.wells.pop() to remove outliers
        visited = []
        discard = []
        for well in self.wells:
            if well not in visited:
                reps = []
                reps += self.originalPlate.repDict[well]
                pairs = combinations(reps,2)
                distMatrix = [[0 for x in range(len(reps))] for y in range(len(reps))]
                for pair in pairs:
                    dist = sqrDiffWellFluoro(self.wells[pair[0]].fluorescence,self.wells[pair[1]].fluorescence)
                    distMatrix[reps.index(pair[0])][reps.index(pair[1])] = dist
                    distMatrix[reps.index(pair[1])][reps.index(pair[0])] = dist
                keep = rh.discardBad(reps,distMatrix,SIMILARITY_THRESHOLD)
                print keep
                for rep in reps:
                    visited.append(rep)
                    if rep not in keep:
                        discard.append(rep)
        print
        print discard
        for well in discard:
            self.wells[well].fluorescence = None
            self.delCurves.append(well)
        return

    def removeInsignificant(self):
        """
        Curves which were normalised with too large of a factor, are considered to
        be within the noise of the experiment, and not used for any  sort of useful 
        analysis. These curves are found and added to self.delCurves (removed from analysis)
        """
        #TODO make sure this method now works AFTER meanCurves and analyseCures have been run
        
        # Searching for curves that are in the noise
        if len(self.plate.noProtein) > 0:
            thresholdm, i = rh.meanSd([self.originalPlate.wells[x].monoThresh for x in self.plate.noProtein])
            for well in self.originalPlate.wells:
                if not self.originalPlate.wells[well].contents.isControl and well not in self.delCurves:
                    if self.originalPlate.wells[well].monoThresh > thresholdm/1.15:
                        #self.wells[well].fluorescence = None
                        self.delCurves.append(well)

        # Searching for curves that have overloaded the sensor
        for well in self.wells:
            if well not in self.delCurves:
                mini = self.wells[well].fluorescence[0]
                maxi = self.wells[well].fluorescence[0]

                maxInd = 0
                for i in range(len(self.wells[well].fluorescence)):
                    if self.wells[well].fluorescence[i] > maxi:
                        maxi = self.wells[well].fluorescence[i]
                        maxInd = i
                    if self.wells[well].fluorescence[i] < mini:
                        mini = self.wells[well].fluorescence[i]

                diff = maxi - mini

                # A boundry defining how much the points can fluctuate and still be considered flat
                lowFlatBoundry = maxi - 0.005*diff

                # Look each way to see how many temperature steps the curve stays flat for
                count = 0
                ind = maxInd - 1
                while ind>=0:
                    if self.wells[well].fluorescence[ind] > lowFlatBoundry:
                        count += 1
                        ind -= 1
                    else:
                        break
                ind = maxInd+1
                while ind<len(self.wells[well].fluorescence):
                    if self.wells[well].fluorescence[ind] > lowFlatBoundry:
                        count += 1 
                        ind += 1
                    else:
                        break
                if well not in self.delCurves and count >= 10:
                    self.delCurves.append(well) 
        return
    
    def analyseCurves(self):
        """
        """
        #gets the maximum point out of all the non normalised graphs
        self.overallMaxNonNormalised = 0
        for well in self.plate.wells.values():
            if well.maxNonNormalised > self.overallMaxNonNormalised:
                self.overallMaxNonNormalised = well.maxNonNormalised
                
        #this is the monotenicity threshold derived for these plate
        self.plate.monotonicThreshold = 0.0005 * self.overallMaxNonNormalised
        self.originalPlate.monotonicThreshold = self.plate.monotonicThreshold
        
        #gets the maximum point out of all the normalised graphs
        #used when plotting the graphs
        self.overallMaxNormalised = 0
        self.overallMinNormalised = 1
        for well in self.plate.wells.values():
            if well.maxNormalised > self.overallMaxNormalised:
                self.overallMaxNormalised = well.maxNormalised
            if well.minNormalised < self.overallMinNormalised:
                self.overallMinNormalised = well.minNormalised
        
        for well in self.originalPlate.names:
            #sets the per-well monotonic threshold,
            self.originalPlate.wells[well].setUniqueMonoThresh(self.plate.monotonicThreshold)

        self.removeInsignificant()
        self.computeTms()
        return
        
    def computeTms(self):
        """
        To find the Tm of a mean curve we look at the curves that comprised it 
        (not including the discarded curves ofcourse) and find the Tm of each of
        those. We then find the mean and sd of these Tms which gives us a Tm estimate, 
        along with an error estimate
        
        When finding the Tm of a curve that is not a mean curve, the error is set to 
        None
        """
        #most calculating is done by getting the mean and sd of replicate Tms,
        #making this the useful part
        for well in self.originalPlate.names:
            #sets own mono instance variable to apropriate state
            self.originalPlate.wells[well].isMonotonic()
            
            print self.originalPlate.wells[well].name, self.originalPlate.wells[well].mono
            
            if self.originalPlate.wells[well].mono == False and well not in self.delCurves:
                self.originalPlate.wells[well].computeTm()
            #monotonic curves are now grouped with complex curves, and plotted as such
            elif self.originalPlate.wells[well].mono:
                if well not in self.delCurves:
                    self.delCurves.append(well)

        for well in self.plate.names:
                tms = [self.originalPlate.wells[x].Tm for x in self.plate.meanDict[well]  if x not in self.delCurves]
                complexs = [self.originalPlate.wells[x].complex for x in self.plate.meanDict[well]  if x not in self.delCurves]
                for data in complexs:
                    if data:
                        self.wells[well].complex = True
                self.wells[well].Tm , self.wells[well].TmError = rh.meanSd(tms)
                if len(tms) == 1:
                    self.wells[well].TmError = None
        return
        
    def returnControlCheck(self):
        """
        Returns a dictionary of the different controls, with values Passed, Failed, or Not found
        depending on if the control passed or wasn't present on the plate. This method is used
        in generate report
        
        The mean of the replicates of each control is what is tested, as this is called after the
        mean plate is created (which updates the 4 control well lists in the plate)
        """
        #initialises all controls to failed
        result = {"lysozyme": "Failed",  #lysozyme Tm check
                  "no dye": "Failed",  #no dye similarity check
                  "no protein": "Failed"}  #no protein similarity check
               
        #test the control if the control is present in the plate
        if len(self.plate.lysozyme)>0:
            #lysozyme Tm check, indexed at 0 since control list has only one item
            if self.plate.wells[self.plate.lysozyme[0]].Tm > LYSOZYME_TM_THRESHOLD[0] - 2*LYSOZYME_TM_THRESHOLD[1] and\
               self.plate.wells[self.plate.lysozyme[0]].Tm < LYSOZYME_TM_THRESHOLD[0] + 2*LYSOZYME_TM_THRESHOLD[1]:
                    result["lysozyme"] = "Passed"
        #control not found
        else:
            result["lysozyme"] = "Not found"
                
        #test the control if the control is present in the plate
        if len(self.plate.noDye)>0:
            #get the curves to compare as series
            noDyeExpected = pandas.Series.from_csv(RUNNING_LOCATION + "\\data\\noDyeControl.csv")
            #indexed at 0 since control list has only one item
            noDyeReal = pandas.Series(self.plate.wells[self.plate.noDye[0]].fluorescence, self.plate.wells[self.plate.noDye[0]].temperatures)
            #if the curves are within required distance from one another, the control is passed
            if rh.sqrdiff(noDyeReal, noDyeExpected) < SIMILARITY_THRESHOLD:
                result["no dye"] = "Passed"
        #control not found
        else:
            result["no dye"] = "Not found"
                
        #test the control if the control is present in the plate
        if len(self.plate.noProtein)>0:
            #get the curves to compare as series
            noProteinExpected = pandas.Series.from_csv(RUNNING_LOCATION + "\\data\\noProteinControl.csv")
            #indexed at 0 since control list has only one item
            noProteinReal = pandas.Series(self.plate.wells[self.plate.noProtein[0]].fluorescence, self.plate.wells[self.plate.noProtein[0]].temperatures)
            #if the curves are within required distance from one another, the control is passed
            if rh.sqrdiff(noProteinReal, noProteinExpected) < SIMILARITY_THRESHOLD:
                result["no protein"] = "Passed"
        #control not found
        else:
                result["no protein"] = "Not Found"
        
        return result
    
    def generateReport(self, outFile):
        """
        Generate a pdf report with the appropriate summary information.
        
        Input: Outfile is the name of the file to which the report is saved
        """
        #======heading, add version here somewhere
        pdf = canvas.Canvas(outFile,pagesize=A4) 
        pdf.setFont("Helvetica-Bold",16)
        pdf.drawString(cm,28*cm,"MELTDOWN")
        pdf.setFont("Helvetica",16)
        pdf.drawString(6*cm,28*cm,"Melt Curve Analysis")

        #======filename and image
        # Remove the file path from the name
        for i in range(1,len(self.name)):
            if self.name[-i] == '/' or self.name[-i] == '\\':
                if -i+40 < 0:
                    nameMatch = self.name[-i+1:-i+40] +"..."
                else:
                    nameMatch = self.name[-i+1:]
                break
        if nameMatch != None:
            pdf.drawString(cm,27*cm, nameMatch)
        else:
            pdf.drawString(cm,27*cm, "..."+self.name[-70:])

        pdf.setFont("Helvetica-Bold",12)
        pdf.drawImage(RUNNING_LOCATION + "\\data\\CSIRO_Grad_RGB_hr.jpg",17*cm,25.5*cm,3.5*cm,3.5*cm)

        #======Highest Tm, at the bottom of the first page
        # For finding the best Tm
        best = ""
        maxi = 0
        for well in self.plate.names:
            # Finding the maximum Tm
            if self.wells[well].contents.isControl == False and self.wells[well].Tm != None and self.wells[well].mono == False and self.wells[well].Tm > maxi:
                maxi = self.wells[well].Tm
                best = well
        # This checks if a maximum Tm has being found. If none it is most likely because no Tms could be calculated
        if best != "":
            if self.wells[best].TmError != None:
                pdf.drawString(3*cm,3.6*cm,"Highest Tm = " + str(round(self.wells[best].Tm,2)) + " +/- " + str(round(self.wells[best].TmError,2)))
            else:
                pdf.drawString(3*cm,3.6*cm,"Highest Tm = " + str(round(self.wells[best].Tm,2)))
            pdf.drawString(3*cm,3*cm,"("+self.wells[best].contents.name+" / "+self.wells[best].contents.salt+")")

        pdf.setFont("Helvetica",12)
        fig1 = plt.figure(num=1,figsize=(10,8))


        #======the summary graph, with diamonds and circles from Tms
        # Maximum and minimum for the y axis of the summary graph
        maxi = 0
        mini = 100
        # Labels for the summary graph
        names = sorted(Contents.name, key=lambda x: x[1])
        labels = [x[0]+"("+str(x[1])+")" for x in names]
        tmHandles = []
        unreliableDrawn = False
        for i, saltConcentration in enumerate(Contents.salt):
            # Tms to be drawn regularly 
            tms = []
            # Tms to be drawn as unreliable
            badTms = []

            for condition in names:
                found = False
                for well in self.plate.names:
                    if self.wells[well].contents.salt == saltConcentration and self.wells[well].contents.name == condition[0] and self.wells[well].contents.pH == condition[1]:
                        if (self.wells[well].Tm != None and len(self.plate.meanDict[well]) > 1 and self.wells[well].TmError == None) or self.wells[well].complex == True:
                            tms.append(None)
                            badTms.append(self.wells[well].Tm)
                        else:
                            tms.append(self.wells[well].Tm)
                            badTms.append(None)
                        found = True
                        break
                # If the particular combination of buffer, salt and pH is not found
                if not found:
                    tms.append(None)
                    badTms.append(None)

            # Figuring out the scale of the y axis for the summary graph
            for val in tms:
                if val != None:
                    if val > maxi:
                        maxi = val
                    if val < mini:
                        mini = val
            for val in badTms:
                if val != None:
                    if val > maxi:
                        maxi = val
                    if val < mini:
                        mini = val
            # Handle for the legend
            try:
                handle, = plt.plot([x for x in range(len(labels))],tms,color=COLOURS[i],marker="o",linestyle="None")
            except IndexError:
                tkMessageBox.showerror("Error", "Only up to 24 types of each condition are supported.\n(there is no limit to the number of conditions)\n\ne.g. 6 different salt concentrations per buffer")
                sys.exit(1)

            plt.plot([x for x in range(len(labels))],badTms,color=COLOURS[i],marker="d",linestyle="None")
            unreliableDrawn = False
            if badTms:
                unreliableDrawn = True
            tmHandles.append(handle)

        originalProteinMeanSd = rh.meanSd([self.originalPlate.wells[x].Tm for x in self.originalPlate.proteinAsSupplied if x not in self.delCurves])
        
        
        # Setting the scale of the y axis
        if originalProteinMeanSd[0]!= None:
            if(originalProteinMeanSd[0]-mini > maxi - originalProteinMeanSd[0]):
                plt.axis([-1,len(labels),mini-5,2*originalProteinMeanSd[0]-mini +10])
            else:
                plt.axis([-1,len(labels),2*originalProteinMeanSd[0] - maxi-5,maxi + 10])
        else:
            plt.axis([-1,len(labels),mini-5,maxi + 5])
        #padding at the top changes depending on how many different condition cvariable 2's there are (legend gets bigger)
        plt.gcf().subplots_adjust(bottom=0.35, top=0.85 - 0.035*(int(len(Contents.salt)/3)))
        plt.ylabel('Tm')

        # Drawing the Tm of the protein as supplied as a horizontal line on the summary graph
        plt.axhline(originalProteinMeanSd[0],0,1,linestyle="--",color="red")
        # Setting x axis labels
        plt.xticks([x for x in range(len(labels))],labels,rotation="vertical")
        # Putting the legend for the summary graph at the top, and show only 1 dot instead of 2
        plt.legend(tmHandles,Contents.salt,loc='lower center', bbox_to_anchor=(0.5, 1),ncol=3, fancybox=True, shadow=False, numpoints=1)
        # Saving the summary graph as an image and drawing it on the page
        imgdata = cStringIO.StringIO()
        fig1.savefig(imgdata, format='png',dpi=180)
        imgdata.seek(0)  # rewind the data
        Image = ImageReader(imgdata)
        pdf.drawImage(Image, cm, 4*cm, 16*cm, 11*cm)  
        plt.close()

        pdf.setFont("Helvetica",10)
        if unreliableDrawn:
            pdf.drawString(7.9*cm, 14.2*cm, "Tms drawn in diamonds may be unreliable")
        unreliableDrawn = False
        


        pdf.setFillColor("black")

        #========the controls, and whether they passed/failed/were not found
        controlChecks = self.returnControlCheck()

        #set colour of the controls
        pdf.setFillColor("blue")
        
        # lysozyme Tm control check
        pdf.drawString(1*cm,16.5*cm,"Lysozyme Control: "+controlChecks["lysozyme"])
        # no dye control check 
        pdf.drawString(1*cm,16*cm,"No Dye Control: "+controlChecks["no dye"])
        # no protein control check
        pdf.drawString(1*cm,15.5*cm,"No Protein Control: "+controlChecks["no protein"])
        
        pdf.setFillColor("black")
        
        #===========writes protein as supplied for the summary graph at bottom of first page
        if originalProteinMeanSd[0]!=None:
            pdf.drawString(15.5*cm,10.4*cm,"Protein as supplied") 
        fig2 = plt.figure(num=1,figsize=(5,4))
        #=========plots the protein as supplied in top left of the front page
        # Plotting the protein as supplied as a control check
        for well in self.originalPlate.proteinAsSupplied:
            if well in self.delCurves:
                plt.plot(self.originalPlate.wells[well].temperatures,self.originalPlate.wells[well].fluorescence\
                , 'grey')
            elif self.originalPlate.wells[well].mono == False:
                plt.plot(self.originalPlate.wells[well].temperatures,self.originalPlate.wells[well].fluorescence\
                , 'g')
            else:
               plt.plot(self.originalPlate.wells[well].temperatures,self.originalPlate.wells[well].fluorescence\
                , 'g',linestyle="--")

        plt.gca().axes.get_yaxis().set_visible(False)
        imgdata = cStringIO.StringIO()
        fig2.savefig(imgdata, format='png',dpi=140)
        imgdata.seek(0)  # rewind the data
        Image = ImageReader(imgdata)
        pdf.drawImage(Image, 0, 18*cm, 8*cm, 6*cm)
        plt.close()

        # Tm of the protein in the oringinal formulation
        try:
            originalProteinMeanSd = rh.meanSd([self.originalPlate.wells[x].Tm for x in self.originalPlate.proteinAsSupplied])
        except:
            # If there is no protein as supplied
            originalProteinMeanSd = (None, None)
        if originalProteinMeanSd[0]!= None:
            pdf.drawString(cm,17.5*cm, "Protein as supplied: Tm = " +str(round(originalProteinMeanSd[0],2))+"(+/-"+str(round(originalProteinMeanSd[1],2))+")")
        else:
            pdf.drawString(cm,17.5*cm, "Protein as supplied: Tm = N/A")

        #================top right Summary box
        pdf.setFont("Helvetica-Bold",13)
        pdf.drawString(8*cm,22.75*cm,"Full interpretation of the results requires you to look ")
        pdf.drawString(8*cm,22.25*cm,"at the individual melt curves.")

        
        avTmError = 0
        count = 0
        tmCount = 0
        for well in self.originalPlate.names:
            if well not in self.originalPlate.lysozyme + self.originalPlate.noDye + self.originalPlate.noProtein + self.originalPlate.proteinAsSupplied:
                if self.originalPlate.wells[well].Tm != None and self.originalPlate.wells[well].mono == False and well not in self.delCurves:
                    tmCount += 1
                count += 1
        tmCount = int(round(tmCount/float(count),2)*100)
        pdf.drawString(8*cm,20.5*cm,str(tmCount)+"%")
        pdf.setFont("Helvetica",13)
        pdf.drawString(9.25*cm,20.5*cm,"of curves were used in Tm estimations")

        count = 0
        for well in self.plate.names:
            if self.wells[well].TmError != None:
                avTmError += self.wells[well].TmError
                count += 1
        pdf.drawString(8*cm,19.5*cm,"Average estimation of error is")
        pdf.setFont("Helvetica-Bold",13)
        if count != 0:
            avTmError = round(avTmError/float(count),1)
        else:
            avTmError = 0
        pdf.drawString(14.1*cm,19.5*cm,str(avTmError)+" C")

        pdf.setFont("Helvetica",13)
        pdf.drawString(8*cm,18.5*cm, "Protein as supplied is")
        pdf.setFont("Helvetica-Bold",13)
        wellBehaved = True

        # If the protein as supplied is not found as a control
        if len(self.originalPlate.proteinAsSupplied) == 0:
            pdf.drawString(12.5*cm,18.5*cm,"not found")
        else:
            # Else find whether it is well behaved or not
            for well in self.originalPlate.proteinAsSupplied:
                if self.originalPlate.wells[well].Tm == None or self.originalPlate.wells[well].mono == True or well in self.delCurves:
                    wellBehaved = False
            if originalProteinMeanSd[1] > 1.5:
                wellBehaved = False
            if wellBehaved:
                pdf.drawString(12.5*cm,18.5*cm,"well behaved")
            else:
                pdf.drawString(12.5*cm,18.5*cm,"not well behaved")

        if wellBehaved == False or avTmError >=1.5 or tmCount <= 50:
            pdf.drawString(8*cm,21.5*cm,"The summary graph appears to be unreliable")

        pdf.rect(7.75*cm,18.05*cm,12*cm,5.4*cm)
        
        #======================================other pages
        # Moving on to the in depth graphs

        # Finding the maximun and minimum flurescence points so that all the graphs can have the same scale
        minYValue = self.overallMinNormalised
        maxYValue = self.overallMaxNormalised

        paddingSize = (maxYValue - minYValue) * 0.05

        fig3 = plt.figure(num=1,figsize=(5,4))



        # Variables used to keep track of where to draw the current graph
        xpos=2
        
        newpage = 1

        if len(Contents.salt) < 6:
            ySize = 9.2
            ypos = 3
            graphNum = 6
            yNum = 3
        elif len(Contents.salt) < 13:
            ySize = 13.8
            ypos = 2
            graphNum = 4
            yNum = 2
        else:
            ySize = 0
            ypos = 1
            graphNum = 2
            yNum = 1

        for sampleContentspH in Contents.name:
            if (newpage-1) % graphNum == 0:
                pdf.showPage()
                pdf.setFont("Helvetica",9)
                pdf.drawString(cm, 1.3*cm,"Curves drawn with dashed lines are unable to be analysed (monotonic, saturated, in the noise, and outliers)")
                pdf.drawString(cm, 0.9*cm,"and are excluded from Tm calculations")
                pdf.drawString(cm, 0.5*cm,"Curves drawn with dotted lines have unreliable estimates for Tms")
                pdf.setFont("Helvetica",12)
            sampleContents = sampleContentspH[0]
            curves = []
            for well in self.originalPlate.names:
                if self.originalPlate.wells[well].contents.name == sampleContents and self.originalPlate.wells[well].contents.pH == sampleContentspH[1]:
                    curves.append(well)
            complexDictionary = {}
            meanWellDictionary = {}
            for i, saltConcentration in enumerate(Contents.salt):
                meanWellDictionary[i] = None
                complexDictionary[i] = False
                for well in curves:
                    if self.originalPlate.wells[well].contents.salt == saltConcentration:
                        if self.originalPlate.wells[well].complex:
                            complexDictionary[i] = True
                            
                        #if curve is in delCurves, plot it dashed. Consists of monotonic curves, curves in the noise,
                        #saturated (flat) curves, and replicate outlier curves
                        if well in self.delCurves:
                            plt.plot(self.originalPlate.wells[well].temperatures,self.originalPlate.wells[well].fluorescence\
                            , COLOURS[i],linestyle="--")
                            
                        #If the curve complex (unreliable Tm), plot it dotted. 
                        #Consists of complex and Tms that are not steep enough
                        elif self.originalPlate.wells[well].complex == True:
                            plt.plot(self.originalPlate.wells[well].temperatures,self.originalPlate.wells[well].fluorescence\
                            , COLOURS[i],linestyle=":")
                            
                        #otherwise plot the graph normally
                        else:
                            plt.plot(self.originalPlate.wells[well].temperatures,self.originalPlate.wells[well].fluorescence\
                            , COLOURS[i])
                            
                        meanWellDictionary[i] = findKey(well,self.plate.meanDict)
                        
            plt.ylim(minYValue-paddingSize,maxYValue+paddingSize)
            plt.gca().axes.get_yaxis().set_visible(False)
            imgdata = cStringIO.StringIO()
            fig3.savefig(imgdata, format='png',dpi=140)
            imgdata.seek(0)  # rewind the data
            Image = ImageReader(imgdata)
            pdf.drawImage(Image, cm+(xpos % 2)*9.5*cm,23.5*cm - (ypos % yNum)*ySize*cm , 8*cm, 6*cm)
            pdf.setFillColor("black")
            pdf.setFont("Helvetica",12)
            pdf.drawString(cm+(xpos % 2)*9.5*cm,23*cm - (ypos % yNum)*ySize*cm ,sampleContents + " (" + str(sampleContentspH[1])+")")
            pdf.setFont("Helvetica",10)
            pdf.drawString(cm+(xpos % 2)*9.5*cm,22.5*cm - (ypos % yNum)*ySize*cm ,"Grouped by")
            pdf.drawString(4.25*cm+(xpos % 2)*9.5*cm,22.5*cm - (ypos % yNum)*ySize*cm ,"Tm")
            drawdpH = False
            offset=0
            for i in range(len(Contents.salt)):
                if Contents.salt[i]:
                    pdf.setFillColor(COLOURS[i])
                    pdf.drawString(cm+(xpos % 2)*9.5*cm,22*cm - (ypos % yNum)*ySize*cm - offset*0.5*cm,Contents.salt[i])
                    if complexDictionary[i]:
                        if meanWellDictionary[i] != None and self.wells[meanWellDictionary[i]].Tm != None:
                            if self.wells[meanWellDictionary[i]].TmError != None:
                                pdf.drawString(4.25*cm+(xpos % 2)*9.5*cm,22*cm - (ypos % yNum)*ySize*cm - offset*0.5*cm ,str(round(self.wells[meanWellDictionary[i]].Tm,2))+" (+/-"+str(round(self.wells[meanWellDictionary[i]].TmError,2))+")^")
                            else:
                                pdf.drawString(4.25*cm+(xpos % 2)*9.5*cm,22*cm - (ypos % yNum)*ySize*cm - offset*0.5*cm ,str(round(self.wells[meanWellDictionary[i]].Tm,2))+"^")
                        else:
                            pdf.drawString(4.25*cm+(xpos % 2)*9.5*cm,22*cm - (ypos % yNum)*ySize*cm - offset*0.5*cm ,"None")
                    else:
                        if meanWellDictionary[i] != None and self.wells[meanWellDictionary[i]].Tm != None:
                            if self.wells[meanWellDictionary[i]].TmError != None:
                                pdf.drawString(4.25*cm+(xpos % 2)*9.5*cm,22*cm - (ypos % yNum)*ySize*cm - offset*0.5*cm ,str(round(self.wells[meanWellDictionary[i]].Tm,2))+" (+/-"+str(round(self.wells[meanWellDictionary[i]].TmError,2))+")")
                            else:
                                pdf.drawString(4.25*cm+(xpos % 2)*9.5*cm,22*cm - (ypos % yNum)*ySize*cm - offset*0.5*cm ,str(round(self.wells[meanWellDictionary[i]].Tm,2)))
                        else:
                            pdf.drawString(4.25*cm+(xpos % 2)*9.5*cm,22*cm - (ypos % yNum)*ySize*cm - offset*0.5*cm ,"None")
                    if meanWellDictionary[i] != None and self.wells[meanWellDictionary[i]].contents.dpH != None and self.wells[meanWellDictionary[i]].contents.dpH != "" and self.wells[meanWellDictionary[i]].Tm != None and self.wells[meanWellDictionary[i]].contents.pH != None and self.wells[meanWellDictionary[i]].contents.pH != "":
                        pdf.drawString(7*cm+(xpos % 2)*9.5*cm,22*cm - (ypos % yNum)*ySize*cm - offset*0.5*cm ,str(round(float(self.wells[meanWellDictionary[i]].contents.pH)+(self.wells[meanWellDictionary[i]].contents.dpH*(self.wells[meanWellDictionary[i]].Tm-20)),2)))
                        pdf.setFillColor("black")
                        if drawdpH ==False:
                            pdf.drawString(7*cm+(xpos % 2)*9.5*cm,22.5*cm - (ypos % yNum)*ySize*cm ,"Adjusted pH at Tm")
                            drawdpH = True
                    offset += 1
            drawdpH = False
            xpos +=1
            if newpage % 2 == 0:
                ypos +=1
            
            newpage += 1 
            plt.close()
            fig3 = plt.figure(num=1,figsize=(5,4))

       
        plt.close()        


        pdf.save()

        return

    def produceNormalisedOutput(self, fileLocAndName):
        with open(fileLocAndName, 'w') as fp:
            fWriter = csv.writer(fp, delimiter='\t')
            fWriter.writerow(['Temperature'] + self.originalPlate.names)
            for i in range(len(self.originalPlate.wells.values()[0].temperatures)):
                #start each row with the temperature
                row = [self.originalPlate.wells.values()[0].temperatures[i]]
                #create each row as the value as that temperature on each well
                for wellName in self.originalPlate.names:
                    row.append(self.originalPlate.wells[wellName].fluorescence[i])
                fWriter.writerow(row)
        return

    
class DSFPlate:
    
    def __init__(self, fluorescenceXLS, labelsXLS):
        """
        A container class that keeps all of the data for a DSF experiment
        organized in an ordered format.  This can be used to quickly
        pull out melt curves for wells, along with their contents.
        Lists of replicates can be found from 2 dictionaries, with key 
        replicate well->mean well or key mean well->replicate wells
        
        repDict, where key is a normal well, and value is all of its replicates
        including itself, e.g. 'A2':['A1','A2','A3']
        
        and meanDict, where key is a mean well, and value is the wells that
        created it, e.g. 'A2':['A4','A5','A6']

        +fluorescenceXLS is the xlsx file that stores all the melt curve data
        
        +labelsXLS is the xlsx file that stores the conditions
        """
        #this is calculated once the curves are analysed
        self.monotonicThreshold = None
        
        #read in the rfu results and the contents map into a pandas dataframe structure
        dataTxt = pandas.DataFrame.from_csv(fluorescenceXLS, sep='\t', index_col='Temperature')
        dataTxt.columns = [str(colName) for colName in dataTxt.columns]
        contentsTxt = pandas.DataFrame.from_csv(labelsXLS, sep='\t', index_col=None)
        #remove any columns that that are blank (default pcrd export includes empty columns sometimes)
        for column in dataTxt:
            if 'Unnamed' in column:
                dataTxt.pop(column)
        for column in contentsTxt:
            if 'Unnamed' in column:
                contentsTxt.pop(column)
        #remove any rows that are all blank (e.g. empty lines at the end of the file)
        dataTxt.dropna(how='all', inplace=True)
        contentsTxt.dropna(how='all', inplace=True)
        
        #names are in order and used to iterate over, wells has each name as a key
        self.names = []
        self.wells = {}
        
        #creating dictionary corresponding to replicates on this plate
        self.repDict = {}
        #creating a dictionary that references every mean plate well, to those that it came from
        self.meanDict = {}
        
        
        #================ reading in from the contents map ====================#
        #well names e.g. A1,A2,etc are imported 1st col
        conditionWellNames = [str(rowName) for rowName in contentsTxt['Well']]
        
        #condition names (the buffer solutions) are imported. 2nd col
        #checks the contents map for a Condition Variable 1 column
        try:
            conditionNames = contentsTxt['Condition Variable 1']
        except KeyError as e:
            tkMessageBox.showerror("Error", "Reading Condition Variable 1 column has failed\n\n"+e.message)
            sys.exit(1)
        
        #empty cells are read in as np.nan (type float) and are converted to ''
        conditionNames = ['' if type(x)!=str and np.isnan(x) else str(x) for x in conditionNames]
        
        #checks contents map for a salt column. 3rd col
        try:
            conditionSalts = contentsTxt['Condition Variable 2']
            #empty cells are read in as np.nan (type float) and are converted to ''
            conditionSalts = ['' if type(x)!=str and np.isnan(x) else str(x) for x in conditionSalts]
        except KeyError:
            conditionSalts = []
            for i in range(len(conditionWellNames)):
                #all conditions have empty string for salt if no salts are given
                conditionSalts.append('')
        except Exception as e:
            tkMessageBox.showerror("Error", "Reading Condition Variable 2 column has failed\n\n"+e.message)
            sys.exit(1)
        
        #checks contents map for a pH column. 4th col
        try:
            conditionPhs = contentsTxt['pH']
            #empty cells are read in as np.nan and are converted to ''
            conditionPhs = ['' if type(x)!=str and np.isnan(x) else float(x) for x in conditionPhs]
        except KeyError:
            conditionPhs = []
            for i in range(len(conditionWellNames)):
                #all conditions have empty string for pH if no Phs are given
                conditionPhs.append('')
        except Exception as e:
            tkMessageBox.showerror("Error", "Reading pH column has failed\n\n"+e.message)
            sys.exit(1)

        
        #checks contents map for a d(pH)/dT column. #5th col
        try:
            conditiondpHdT = contentsTxt['d(pH)/dT']
            #empty cells are read in as np.nan and are converted to ''
            conditiondpHdT = ['' if type(x)!=str and np.isnan(x) else float(x) for x in conditiondpHdT]
        except KeyError:
            conditiondpHdT=[]
            for i in range(len(conditionWellNames)):
                #all conditions have emty string for dpH/dT if no dph/dt values are given
                conditiondpHdT.append('')
        except Exception as e:
            tkMessageBox.showerror("Error", "Reading d(pH)/dT column has failed\n\n"+e.message)
            sys.exit(1)
                
        #checks contents map for a control column. #6th col
        try:
            conditionIsControl = contentsTxt['Control']
            #empty cells are read in as np.nan and are converted to ''
            conditionIsControl = ['' if type(x)!=str and np.isnan(x) else int(x) for x in conditionIsControl]
        except KeyError:
            conditionIsControl = []
            for i in range(len(conditionWellNames)):
                #all conditions have empty string for control if column isnt given
                conditionIsControl.append('')
        except Exception as e:
            tkMessageBox.showerror("Error", "Reading Control column has failed\n\n"+e.message)
            sys.exit(1)
      
        #==================================================================#     
                
        
        #saves the list of names in the Plate for future use
        self.names = conditionWellNames
        
        #control well locations, filled when creating replicate dictionary
        #uses names of controls from global list CONTROL_WELL_NAMES
        self.lysozyme = []
        self.noDye = []
        self.proteinAsSupplied = []
        self.noProtein = []
        #the names of the controls are gotten from the global list at the top of the file,
        #note that the order in that list is important

        #checks if wells are the controls that we know to check for, and forces a 
        #1 in the control column if they are
        for i,condition in enumerate(conditionNames):
            if condition.lower() == "lysozyme":
                self.lysozyme.append(conditionWellNames[i])
                conditionIsControl[i] = 1.0
            elif condition.lower() == "no dye":
                self.noDye.append(conditionWellNames[i])
                conditionIsControl[i] = 1.0
            elif condition.lower() == "protein as supplied":
                self.proteinAsSupplied.append(conditionWellNames[i])
                conditionIsControl[i] = 1.0
            elif condition.lower() == "no protein":
                self.noProtein.append(conditionWellNames[i])
                conditionIsControl[i] = 1.0
                
        
        #dictionary keys are a single well, with value a list of its reps and itself, e.g. 'A2':['A1','A2','A3']
        self.repDict = {}
        for i, well in enumerate(conditionWellNames):
            #create and entry is one doesnt exist already
            if well not in self.repDict.keys():
                self.repDict[well] = []
            for j, conditionTuple in enumerate(zip(conditionNames, conditionSalts, conditionPhs)):
                #if we find another well with the same name, ph and salt, it is a replicate
                if conditionTuple == zip(conditionNames, conditionSalts, conditionPhs)[i]:
                    self.repDict[well].append(conditionWellNames[j])
        
        for i,name in enumerate(conditionWellNames):
            #creates a pandas series of each well, with index being temperature, and values fluorescence
            fluoroSeries = dataTxt[name]
            #populate the well dictionary of labels and values
            self.wells[name] = DSFWell(fluoroSeries, conditionNames[i], conditionSalts[i], conditionPhs[i], conditiondpHdT[i], conditionIsControl[i])
            
        return
              

class DSFWell:
    
    def __init__(self, fluorescenceSeries, conditionName, conditionSalt, conditionPh, conditiondpHdT, conditionIsControl):
        """
        A well class that holds all of the data to characterize
        a well in a buffer plate.
        
        +fluorescenceSeries is a pandas Series describing the melt curve for a single well
        
        +conditionName is a buffer condition.
        +conditionSalt is a salt concentration.
        +conditionPh is a pH value.
        +conditiondpHdT is a dPh/dT value.
        +conditionIsControl is a control flag, where '1' signifies the well is a control.
        
        From the series a well is given a name, its list of temperatures, and its curve"""
        #name, temperatures, and curve from data
        self.name = fluorescenceSeries.name
        self.temperatures = fluorescenceSeries.index
        self.fluorescence = [x for x in fluorescenceSeries]

        stepSize = self.temperatures[1]-self.temperatures[0]
        
        #from the non normalised curve we get the max  for each individual curve
        #the overall max on the plate will decide what the monotenicity threshold for the experiment will be
        self.maxNonNormalised = 0
        for x in self.fluorescence:
            if x > self.maxNonNormalised:
                self.maxNonNormalised = x
        
        #================= normalisation happens here ================#
        #the curve is then normalised to have an area below the curve of 1
        count = 0
        for height in self.fluorescence:
            count += height*stepSize
        self.fluorescence = [x / count for x in self.fluorescence]
        #used to calculate the monotenicity threshold
        self.normalisationFactor = count
        
        #from the now normalised curve we get the max and min for each individual curve
        #this is used in complex detection and plotting
        self.maxNormalised = self.maxNonNormalised / count
        self.minNormalised = 1
        for x in self.fluorescence:
            if x < self.minNormalised:
                self.minNormalised = x
        
        #other attributes of the curve are set to false/none until later analysis of the curve
        self.complex = False
        self.mono = False
        #tm and tm error are calulated upon calling the computeTm() method
        self.Tm = None   
        self.TmError = None
        
        #the contents of the well is contained in an object of Contents inside well
        self.contents = Contents(conditionName, conditionSalt, conditionPh, conditiondpHdT, conditionIsControl)
        return  

    def setUniqueMonoThresh(self, monoThreshold):
        #the forgive monotonic threshold depends on the normalisation of the curve
        self.monoThresh = monoThreshold / self.normalisationFactor
        return
        
    def isMonotonic(self):
        """
        Checks to see if the normalised curve, and hence original curve, is monotonic non-increasing
        
        This is done by looking at each consecutive point, forgiving an amount of monoThresh, and seeing if it
        it contradicts this, and is higher than the previous. 5 such consecutive points decide the curve 
        is not monotonic, with each decreasing pair of points inbetween, puts the consecutive contradiction 
        count back down by 1.
        """

        #assume monotonic non-increasing
        nonIncreasingMono = True
        contradictions = 0
        prev=self.fluorescence[0]
        for point in self.fluorescence[1:]:
            if point > prev+self.monoThresh:
                #found contradiction, even with forgive threshold, need (5) contradictions with less than (5)
                #non-contradicting points between them to be able to say it is not monotonically non-increasing
                contradictions+=1
                
            elif point < prev+self.monoThresh:
                #lower contradiction counter, if points are non-increasing as assumed, but not below 0
                if contradictions!=0:
                    contradictions-=1
                    
            #when point=previous do nothing with the contradiction counter
                    
            if contradictions == 5:
                #if 5 contradictions, it is definately not monotonic non-increasing
                nonIncreasingMono=False
                break
            prev=point
            
        #if it is non-increasing set mono to true and end now
        if nonIncreasingMono:
            self.mono = True
            return

        #if not non-increasing, then func is not monotonic
        self.mono = False
        return
        
    
    def computeTm(self):
        """
        Finds the temperature value corresponding to the Tm of a well curve. This is done 
        by finding the lowest point on the derivative of the well, fitting a parabola 
        to it and its two neighbouring indices, and taking the minimum (turning point) 
        of the parabola
        
        The well curve is also checked for having a 'complex' shape, in which case the report
        states that the Tm calculated might be unreliable. 
        This is calculated by finding the minimum and the maximum of of the curve, and seeing if there
        are any turning points between the two. If so, the curve shape is complex
        """
        #first step  is finding the derivative series of the well
        x = self.temperatures
        if self.fluorescence == None:
            self.Tm = None
            return
        y = self.fluorescence
    
        xdiff = np.diff(x)
        dydx = -np.diff(y)/xdiff
        #the derivative series, has one less index since there is one fewer differences than points
        seriesDeriv = pandas.Series(dydx, x[:-1])
        
        #now that we have the derivative series, we can find the Tm
        lowestPoint = 0
        lowestPointIndex = None
        
        #gets number of signchanges between max and min of the curve, used to determin if the curve
        #is complex or not
        lowestPoint2 = 1
        lowestIndex2 = None
        highestPoint = 0
        highestIndex = None
        previous = None
        for i, value in enumerate(self.fluorescence[:-1]):
            if value > highestPoint:
                highestPoint = value
                highestIndex = i
        if highestIndex == 0 :
            highestPoint = 0
            highestIndex = None
            for i, value in enumerate(self.fluorescence[:-1]):
                if value<lowestPoint2:
                    lowestPoint2 = value
                    lowestIndex2 = i
            for i, value in enumerate(self.fluorescence[:-1]):
                if i < lowestIndex2:
                    continue
                if value > highestPoint:
                    highestPoint = value
                    highestIndex = i
        else:
            for i, value in enumerate(self.fluorescence[:-1]):
                if i > highestIndex:
                    break
                if value<lowestPoint2:
                    lowestPoint2 = value
                    lowestIndex2 = i
        signChange = False
        for ind in seriesDeriv.index[lowestIndex2+1:highestIndex]:
        
            if previous:
                if seriesDeriv[ind] + SIGN_CHANGE_THRESH < 0 and previous - SIGN_CHANGE_THRESH > 0:
                    signChange = True
                if seriesDeriv[ind] - SIGN_CHANGE_THRESH > 0 and previous + SIGN_CHANGE_THRESH < 0:
                    signChange = True
                # if seriesDeriv[ind] == 0:
                #     signChangeCount += 1
            previous = seriesDeriv[ind]

            
        #finding the lowest point and its index on the derivative series
        #only search for Tm up to 90degrees, since last part is hard to predict
        #and often gives false positives
        ignoreNum = int(len(seriesDeriv.index)*0.125)
        for ind in seriesDeriv.index[:-ignoreNum]:
            if seriesDeriv[ind]<lowestPoint:
                lowestPoint = seriesDeriv[ind]
                lowestPointIndex = ind
        
        #TODO working, tms not steep enough added to complex
        #if the slope is not steep enough, tm remains saved, but curve is grouped with the
        #complex curves (now known as the unreliable group)
        #if lowestPoint > -0.000001 / (normalisationFactor / saturation max point of all curves thing):
        #    print self.name, 'lowestpoint too small', lowestPoint
        #    self.complex = True

        #if lowest point is the first index, then no curve fit is required
        if lowestPointIndex == seriesDeriv.index[0]:
            tm = lowestPointIndex
            self.Tm = tm
            
            #set complex to true if curve was complex
            if signChange:
                self.complex = True
            return
    
        #could not find any Tm
        if lowestPointIndex == None:
            self.Tm = None
            
            #if no tm, the curve hopefully be picked up as a monotonic/in the noise/saturated/outlier
            #however, if this does not happen, the curve remains as complex
            self.complex = True
            return     
        
        #the indices in the series either side of the lowest index
        #note the first list is indexed e.g. list[i] where i is the section using .index
        leftIndex = [ind for ind in seriesDeriv.index][[ind for ind in seriesDeriv.index].index(lowestPointIndex)-1]
        rightIndex = [ind for ind in seriesDeriv.index][[ind for ind in seriesDeriv.index].index(lowestPointIndex)+1]
        
        
        #matrices used to fit a parabola to the 3 points
        Y=[seriesDeriv[leftIndex],
           seriesDeriv[lowestPointIndex],
           seriesDeriv[rightIndex]]
           
        A=[[leftIndex**2,   leftIndex,   1],
           [lowestPointIndex**2, lowestPointIndex, 1],
           [rightIndex**2,  rightIndex,  1]]
           
        #solve for b, in the form Y=Ab
        (a,b,c) = np.linalg.solve(A,Y)
        
        #initialise tm to left most point of relevant curve
        tm=seriesDeriv[leftIndex]
        tmValue=0
        #make tm the lowest point on the fitted parabola rounded to nearest 0.01
        for x in np.arange(leftIndex,rightIndex,0.01):
            point = (a*(x**2) + b*x + c)
            if tmValue > point:
                tmValue = point
                tm = x
        self.Tm = tm
        
        #again check for complex shape before returning
        if signChange:
            self.complex = True


        averagePoint = (lowestPoint2 +highestPoint) / 2
        i = lowestIndex2
        while self.fluorescence[i]<averagePoint:
            i += 1;

        # estimates tm by another method and if the difference is too large the curve is considred complex
        if (self.temperatures[i] -self.Tm)**2 > 5**2:
            self.complex=True
        return

class Contents:
    """
    Keeps a static variable of all the different salt concentrtions and names in 
    the experiment as this is used for plotting in the report
    """
    salt = []
    name = []
    def __init__(self, conditionName, conditionSalt, conditionPh, conditiondpHdT, conditionIsControl):
        """
        Struct class for the contents of a well, stores the name, pH, salt, 
        dpH, and whether it is a control for each well.
        """
        self.name = conditionName
        self.salt = conditionSalt
        self.pH = conditionPh
        self.dpH = conditiondpHdT
        #whether or not the well is a control is saved as a boolean in each well
        self.isControl = True
        if conditionIsControl != 1:
            self.isControl = False
            
        #add names and salts to the static lists if not already present
        key = (self.name, self.pH)
        if key not in Contents.name and self.name != "" and self.isControl == False:
            Contents.name.append(key)
        if self.salt not in Contents.salt and self.salt != "":
            Contents.salt.append(self.salt)
        #only add empty string as a type is its used in non-controls
        if self.salt not in Contents.salt and self.salt == "" and self.isControl != 1:
            Contents.salt.append(self.salt)
        return

        

#==============Functions that can be used to replicate thresholds==============#
def determineOutlierThreshold(listOfLysozymeWellNames, pathrfu, pathContentsMap):
    """
    Used to reproduce the threshold when determining what curves
    are outliers from a group of replicates
    e.g. listOfLysozymeWellNames = ["A1","A2","A3"] (as on bufferscreen9)
    """
    lysozyme=[]
    results = []

    #the path to a directory of exported RFU result files
    files = os.listdir(pathrfu)
    pathrfu = pathrfu + "/"
    for data in files:
        #creates each  plate
        plate = DSFPlate(pathrfu+data, pathContentsMap)
        for well in listOfLysozymeWellNames:
            lysozyme.append(plate.wells[well].fluorescence)
    for pair in combinations(lysozyme,2):
        results.append(sqrDiffWellFluoro(pair[0],pair[1]))
    total = 0
    for num in results:
        total+=num
    return total/len(results)
    
def lysozymeAllTm(pathder,wells):
    """
    Calculates the mean and standard deviation of the lysozyme Tm, used when checking controls
    in the experiment
    
    +pathder is the path to the folder containing all and only the rfu derivative
    results from a lot of experiments which contain lysozyme in some wells
    
    +wells is  a list of the wells on the plate that coorrespond to the location
    of lysozyme on the plate e.g. ["A1","A2","A3"]
    """
    Tms=[]
    pathder = pathder + "/"
    for data in os.listdir(pathder):
        df = pandas.DataFrame.from_csv(pathder+data,index_col=1)
        df.pop("Unnamed: 0")
        for well in wells:
            series = df[well]
            mini = 100
            Tm = -1
            for x in series.index:
                if series[x] < mini:
                    mini = series[x]
                    Tm = x
            Tms.append(Tm)
    return rh.meanSd(Tms)
#==============================================================================#


#useful small functions used throughout
#================================================#
def findKey(value,dict):
    """
    Takes a dictionary and a value and returns the first key it finds that corresponds to that value
    """
    for key, val in dict.iteritems():
        if value in val:
            return key


def meanCurve(curves):
    """
    Takes in a list of lists (list of individual curves) and returns a single list
    that is the mean curve of the ones supplied
    """
    mean = []
    for i in range(len(curves[0])):
        mean += [0]
    for curve in curves:
        for i in range(len(curve)):
            mean[i] += curve[i]
    return [x /len(curves) for x in mean]


def sqrDiffWellFluoro(fluoro1,fluoro2):
    """
    Gets the sum of squared differences between every pair of points in two fuorescence curves
    """
    dist = 0
    count = 0
    x1 = [math.log(x) for x in fluoro1]
    x2 = [math.log(x) for x in fluoro2]
    while count < len(fluoro1):
        dist += math.pow(x1[count]-x2[count],2)
        count += 1
    return dist
#================================================#


def main():
    """
    parse arguments and call classes/functions needed for DSF analysis
    """
    #opens up windows for user to selec files
    root = Tkinter.Tk()
    root.withdraw()
 
    #DSF results file
    rfuFilepath = tkFileDialog.askopenfilename(title="Select the DSF results", filetypes=[("text files", ".txt")])
    # contents map, or default cfx manager summary file
    contentsMapFilepath = tkFileDialog.askopenfilename(title="Select the contents map", filetypes=[("text files", ".txt")])
    try:
        #the analysis
        print 'reading in data ...'
        mydsf = DSFAnalysis()
        mydsf.loadMeltCurves(rfuFilepath,contentsMapFilepath)
        print 'analysing ...'
        mydsf.analyseCurves()
        
        
        
        # generates the report
        print 'generating report ...'
        name = rfuFilepath.split(".")[0]
        mydsf.generateReport(name+".pdf")

        #also remove the exported xls/xlsx files after meltdown has been run on them
        #find the protein name, then all the files with that name in it, then delete them
        if DELETE_INPUT_FILES:
            print 'deleting input data file ...'
            folder = rfuFilepath[:-len(rfuFilepath.split('/')[-1]) - 1]
            proteinName = rfuFilepath.split('/')[-1].split()[0]
            for fl in os.listdir(folder):
                if '.pdf' in fl:
                    continue
                if proteinName in fl:
                    os.remove(folder+'/'+fl)
                    
        #generate a tab delimited .txt file of the normalised curves, if the setting in the ini
        #is set to true
        if CREATE_NORMALISED_DATA:
            #add -normalised to the end of the filename
            print 'creating normalised data ...'
            mydsf.produceNormalisedOutput(rfuFilepath[:-4] + '-normalised.txt')
        
        print '*done*'
            
        
    except:
        errors = open(RUNNING_LOCATION + "\\error_log.txt",'w')
        etype, value, tb = sys.exc_info()
        errors.write(version+"\n")
        errors.write(''.join(traceback.format_exception(etype, value, tb, None))) 
        root = Tkinter.Tk()
        root.withdraw()
        print '*error occured, check error log*'
        tkMessageBox.showerror("Error", "Check error log")
        errors.close()

    return

#excecutes main() on file run
if __name__ == "__main__":
    main()

#can be used for batch analysis of experiments with the same contents map
"""
loc = ""
contents = ""
i=0
for file_ in os.listdir(loc):
    rfuFilepath = loc + file_
    print rfuFilepath
    mydsf = DSFAnalysis()
    mydsf.loadMeltCurves(rfuFilepath,contents)
    mydsf.analyseCurves()
    mydsf.removeInsignificant()
    
    # generates the report
    name = rfuFilepath.split(".")[0]
    mydsf.generateReport(name+".pdf")
    
    if i == 10:
        break
    i+=1
"""












