# coding=utf-8
from __future__ import absolute_import
import octoprint.plugin

import time
import os
import sys
from .settings import OctolapseSettings
from .gcode import *
from .snapshot import CaptureSnapshot,SnapshotInfo
from .position import *
from octoprint.events import eventManager, Events
from .trigger import *
import itertools
from .utility import *
from .render import Render
class OctolapsePlugin(	octoprint.plugin.SettingsPlugin,
						octoprint.plugin.AssetPlugin,
						octoprint.plugin.TemplatePlugin,
						octoprint.plugin.StartupPlugin,
						octoprint.plugin.EventHandlerPlugin):
	TIMEOUT_DELAY = 1000
	IsStarted = False
	def __init__(self):
		self.OctolapseGcode = None
		self.CaptureSnapshot = None
		self.PrintStartTime = time.time()
		self.Settings = None
		self.Triggers = []
		self.Position = None
		self.IsPausedByOctolapse = False
		self.SnapshotGcode = None
		self.SnapshotCount = 0
		self._IsTriggering = False
		self.WaitForSnapshot = False
		self.Render = None
		self.IsRendering = False
	##~~ After Startup
	def on_after_startup(self):
		self.reload_settings()
		self._logger.info("Octolapse - loaded and active.")
		IsStarted = True

	def reload_settings(self):
		if(self._settings is None):
			self._logger.error("The plugin settings (_settings) is None!")
			return
		self.Settings = OctolapseSettings(self._logger,self._settings)
		#self._logger.info("Octolapse - Octoprint settings converted to octolapse settings: {0}".format(settings.GetSettingsForOctoprint(self._logger,self.Settings)))
	##~~ SettingsPlugin mixin

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
		self.Settings.debug.LogSettingsSave('Settings Saved: {0}'.format(data))

	def get_settings_defaults(self):
		defaultSettings = settings.GetSettingsForOctoprint(self._logger,None)
		self._logger.info("Octolapse - creating default settings: {0}".format(defaultSettings))
		return defaultSettings

	def get_template_configs(self):
		self._logger.info("Octolapse - is loading template configurations.")
		return [dict(type="settings", custom_bindings=False)]

	def CurrentPrinterProfile(self):
		return self._printer_profile_manager.get_current()

	
	## EventHandlerPlugin mixin
	def on_event(self, event, payload):

		if(self.Settings is None or not self.Settings.is_octolapse_enabled):
			return
		if (event == Events.PRINT_PAUSED):
			if(not self.IsPausedByOctolapse):
				self.OnPrintPause()
			else:
				self.OnPrintPausedByOctolapse()
		elif (event == Events.PRINT_RESUMED):
			self.OnPrintResumed()
		elif (event == Events.PRINT_STARTED):
			self.OnPrintStart()
		elif (event == Events.PRINT_FAILED):
			self.OnPrintFailed()
		elif (event == Events.PRINT_CANCELLED):
			self.OnPrintCancelled()
		elif (event == Events.PRINT_DONE):
			self._logger.info("Octolapse - Print Done")
			self.OnPrintCompleted()
		

	def ClearTriggers(self):
		self.Triggers[:] = []
	def OnPrintResumed(self):
		self.IsPausedByOctolapse = False
		self.SnapshotGcode = None
		self.Settings.debug.LogPrintStateChange("Print Resumed.")

	def OnPrintPause(self):
		self.Settings.debug.LogPrintStateChange("Print Paused.")
		if(self.Triggers is not None and len(self.Triggers)>0):
			for trigger in self.Triggers:
				if(type(trigger) == TimerTrigger):
					trigger.Pause()
	def OnPrintPausedByOctolapse(self):
		self.Settings.debug.LogPrintStateChange("Print Paused by Octolapse.")
		self.SendSnapshotGcode()
	def OnPrintStart(self):
		self.Settings.debug.LogPrintStateChange("Octolapse - Print Started.")
		self.reload_settings()				
		self.OctolapseGcode = Gcode(self.Settings.printer, self.Settings.CurrentProfile(),self.CurrentPrinterProfile(),self.Settings.debug)
		self.CaptureSnapshot = CaptureSnapshot(self.Settings.CurrentProfile(), self.Settings.printer,self.Settings.debug)
		if(not self.IsRendering):
			self.CaptureSnapshot.CleanSnapshots(None,'before-print')
		self.ClearTriggers()
		self.Position = Position(self.CurrentPrinterProfile(),self.Settings.debug,self.Settings.printer.z_min,self.Settings.printer.z_hop,self.Settings.printer.is_e_relative)
		self.Render = Render(self.Settings.debug, self.Settings.CurrentProfile(),1,self.OnRenderStart,self.OnRenderFail,self.OnRenderComplete,None)
		self.SnapshotCount = 0
		self.CaptureSnapshot.SetPrintStartTime(time.time())
		self.CaptureSnapshot.SetPrintEndTime(None)
		self.IsPausedByOctolapse = False
		self.WaitForSnapshot = False
		# create the triggers for this print
		snapshot = self.Settings.CurrentProfile().snapshot
		# If the gcode trigger is enabled, add it
		if(snapshot.gcode_trigger_enabled):
			#Configure the extruder triggers
			self.Settings.debug.LogInfo("Creating Gcode Trigger - Gcode Command:{0}, RequireZHop:{1}".format(self.Settings.printer.snapshot_command, snapshot.gcode_trigger_require_zhop))
			self.Settings.debug.LogInfo("Extruder Triggers - On Extruding:{0}, On Extruding Start:{1}, On Primed:{2}, On Retracting:{3}, On Retracted:{4}, On Detracting:{5}"
				.format(snapshot.gcode_trigger_on_extruding
					,snapshot.gcode_trigger_on_extruding_start
					,snapshot.gcode_trigger_on_primed
					,snapshot.gcode_trigger_on_retracting
					,snapshot.gcode_trigger_on_retracted
					,snapshot.gcode_trigger_on_detracting)
			)
			gcodeExtruderTriggers = ExtruderTriggers(snapshot.gcode_trigger_on_extruding
				,snapshot.gcode_trigger_on_extruding_start
				,snapshot.gcode_trigger_on_primed
				,snapshot.gcode_trigger_on_retracting
				,snapshot.gcode_trigger_on_retracted
				,snapshot.gcode_trigger_on_detracting)
			#Add the trigger to the list
			self.Triggers.append(
				GcodeTrigger(
					gcodeExtruderTriggers,self.Settings.debug,self.Settings.printer.snapshot_command, snapshot.gcode_trigger_require_zhop
			))
		# If the layer trigger is enabled, add it
		if(snapshot.layer_trigger_enabled):
			#Configure the extruder triggers
			self.Settings.debug.LogInfo("Creating Layer Trigger - TriggerHeight:{0} (none = layer change), RequiresZHop:{1}".format(snapshot.layer_trigger_height, snapshot.layer_trigger_require_zhop))
			self.Settings.debug.LogInfo("Extruder Triggers - On Extruding:{0}, On Extruding Start:{1}, On Primed:{2}, On Retracting:{3}, On Retracted:{4}, On Detracting:{5}"
				.format(
					snapshot.layer_trigger_on_extruding
					,snapshot.layer_trigger_on_extruding_start
					,snapshot.layer_trigger_on_primed
					,snapshot.layer_trigger_on_retracting
					,snapshot.layer_trigger_on_retracted
					,snapshot.layer_trigger_on_detracting)
			)
			layerExtruderTriggers = ExtruderTriggers(
				snapshot.layer_trigger_on_extruding
				,snapshot.layer_trigger_on_extruding_start
				,snapshot.layer_trigger_on_primed
				,snapshot.layer_trigger_on_retracting
				,snapshot.layer_trigger_on_retracted
				,snapshot.layer_trigger_on_detracting)
			self.Triggers.append(LayerTrigger(layerExtruderTriggers,self.Settings.debug, snapshot.layer_trigger_require_zhop, snapshot.layer_trigger_height))
		# If the layer trigger is enabled, add it
		if(snapshot.timer_trigger_enabled):
			#Configure the extruder triggers
			self.Settings.debug.LogInfo("Creating Timer Trigger - Seconds:{0}, RequireZHop:{1}".format(snapshot.timer_trigger_seconds, snapshot.timer_trigger_require_zhop))
			self.Settings.debug.LogInfo("Extruder Triggers - On Extruding:{0}, On Extruding Start:{1}, On Primed:{2}, On Retracting:{3}, On Retracted:{4}, On Detracting:{5}"
				.format(
					snapshot.timer_trigger_on_extruding
					,snapshot.timer_trigger_on_extruding_start
					,snapshot.timer_trigger_on_primed
					,snapshot.timer_trigger_on_retracting
					,snapshot.timer_trigger_on_retracted
					,snapshot.timer_trigger_on_detracting)
			)
			#Configure the extruder triggers
			timerExtruderTriggers = ExtruderTriggers(
				snapshot.timer_trigger_on_extruding
				,snapshot.timer_trigger_on_extruding_start
				,snapshot.timer_trigger_on_primed
				,snapshot.timer_trigger_on_retracting
				,snapshot.timer_trigger_on_retracted
				,snapshot.timer_trigger_on_detracting)
			self.Triggers.append(TimerTrigger(timerExtruderTriggers,self.Settings.debug,snapshot.timer_trigger_seconds,snapshot.timer_trigger_require_zhop))

	def OnPrintFailed(self):
		self.Settings.debug.LogPrintStateChange("Print Failed.")
		self.Render.Process(self.CurrentlyPrintingFileName(),  self.CaptureSnapshot.PrintStartTime, self.CaptureSnapshot.PrintEndTime);
		self.Settings.debug.LogInfo("Started Rendering Timelapse");
		if(not self.IsRendering):
			self.CaptureSnapshot.CleanSnapshots(self.CurrentlyPrintingFileName(),'after-failed')
		self.OnPrintEnd()
	def OnPrintCancelled(self):
		self.Settings.debug.LogPrintStateChange("Print Cancelled.")
		self.Render.Process(self.CurrentlyPrintingFileName(),  self.CaptureSnapshot.PrintStartTime, self.CaptureSnapshot.PrintEndTime);
		self.Settings.debug.LogInfo("Started Rendering Timelapse");
		if(not self.IsRendering):
			self.CaptureSnapshot.CleanSnapshots(self.CurrentlyPrintingFileName(),'after-cancel')
		self.OnPrintEnd()
	def OnPrintCompleted(self):
		self.CaptureSnapshot.SetPrintEndTime(time.time())
		self.Render.Process(self.CurrentlyPrintingFileName(),  self.CaptureSnapshot.PrintStartTime, self.CaptureSnapshot.PrintEndTime);
		self.Settings.debug.LogInfo("Started Rendering Timelapse");
		self.Settings.debug.LogPrintStateChange("Print Completed!")
		if(not self.IsRendering):
			self.CaptureSnapshot.CleanSnapshots(self.CurrentlyPrintingFileName(),'after-print')
		self.OnPrintEnd()

	def OnPrintEnd(self):
		
		self.ClearTriggers()
		self.Position = None


	def OnRenderStart(self):
		self.IsRendering = False

	def OnRenderComplete(self, *args, **kwargs):
		self.IsRendering = False
		self.CaptureSnapshot.CleanSnapshots(self.CurrentlyPrintingFileName(),'after_render_complete')
		self.Settings.debug.LogInfo("Rendering Complete");
	def OnRenderFail(self, *args, **kwargs):
		self.IsRendering = False
		self.CaptureSnapshot.CleanSnapshots(self.CurrentlyPrintingFileName(),'after_render_fail')
		self.Settings.debug.LogInfo("Rendering Failed");

	def CurrentlyPrintingFileName(self):
		if(self._printer is not None):
			current_job = self._printer.get_current_job()
			if current_job is not None and "file" in current_job:
				current_job_file = current_job["file"]
				if "path" in current_job_file and "origin" in current_job_file:
					current_file_path = current_job_file["path"]
					return utility.GetFilenameFromFullPath(current_file_path)
		return ""
	
	
	def GcodeQueuing(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		# update the position tracker so that we know where all of the axis are.
		# We will need this later when generating snapshot gcode so that we can return to the previous
		# position
		#

		# check for assert commands
		if(self.Settings is not None):
			
			self.Settings.debug.ApplyCommands(cmd, triggers=self.Triggers, isSnapshot=self.IsPausedByOctolapse)

		if(self.Position is not None):
			self.Position.Update(cmd)
		# preconditions
		if (# wait for the snapshot command to finish sending, or wait for the snapshot delay in case of timeouts)
			self.Settings is None
			or not self.Settings.is_octolapse_enabled
			or self.Triggers is None
			or len(self.Triggers)<1
			or self._printer is None
			or self.IsPausedByOctolapse
			):
			return cmd
		currentTrigger = trigger.IsTriggering(self.Triggers,self.Position, cmd, self.Settings.debug)
		if(currentTrigger is not None):
			#We're triggering
			self.SnapshotGcode = self.OctolapseGcode.GetSnapshotGcode(self.Position,self.Position.Extruder)
			# build an array of commands to take the snapshot
			if(self.SnapshotGcode is not None and not self.IsPausedByOctolapse):
				self.Settings.debug.LogSnapshotGcodeEndcommand("End Gcode Command:{0}".format(self.SnapshotGcode.ReturnEndCommand()))
				self.SnapshotGcode.SavedCommand = cmd
				self.IsPausedByOctolapse = True
				self._printer.pause_print()
				return None
			else:
				self.Settings.debug.LogError("Cannot take a snapshot, there are no snapshot gcode commands to execute!  Check your profile settings or re-install.")

		if( trigger.IsSnapshotCommand(cmd,self.Settings.printer.snapshot_command)):
			cmd = None
		return cmd
	
	
	def GcodeSent(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		if(self.Settings is None
			or not self.Settings.is_octolapse_enabled
			or self.Triggers is None
			or len(self.Triggers)<1
			or self._printer is None):
			return

		if(self.SnapshotGcode is not None and not self.WaitForSnapshot):
			self.Settings.debug.LogSnapshotDownload("Looking for EndGcode:{0} - Current Gcode:{1}, Parsed Gcode:{2}".format(self.SnapshotGcode.StartEndCommand(),cmd,gcode))
			if(self.SnapshotGcode.StartEndCommand() == cmd):
				self.Settings.debug.LogSnapshotGcodeEndcommand("End Snapshot Gcode Command Found:{0}. Waiting for snapshot.".format(self.SnapshotGcode.StartEndCommand()))
				self.WaitForSnapshot = True
				
	def GcodeReceived(self, comm, line, *args, **kwargs):
		if(self.IsPausedByOctolapse and self.WaitForSnapshot):
			self.Settings.debug.LogSnapshotGcodeEndcommand("End wait for snapshot:{0}".format(line))
			self.IsPausedByOctolapse = False
			self.SnapshotGcode = None
			self.WaitForSnapshot = False
			self.TakeSnapshot()
			self._printer.resume_print()
		return line

	def SendSnapshotGcode(self):
		if(self.SnapshotGcode is None):
			self.Settings.debug.LogError("Cannot send snapshot Gcode, no gcode returned")
		returnCommands = self.SnapshotGcode.ReturnCommands
		savedCommand = self.SnapshotGcode.SavedCommand
		# Send commands to move to the snapshot position
		self._printer.commands(self.SnapshotGcode.StartCommands);
		# Start the return journey!
		self._printer.commands(returnCommands)
		self._printer.commands(savedCommand);
		

	def TakeSnapshot(self):
		snapshot = self.CaptureSnapshot
		self.SnapshotCount += 1
		if(snapshot is not None):
			try:
				snapshot.Snap(self.CurrentlyPrintingFileName(),self.SnapshotCount)
			except:
					
				a = sys.exc_info() # Info about unknown error that caused exception.                                              
				errorMessage = "    {0}".format(a)
				b = [ str(p) for p in a ]
				errorMessage += "\n    {0}".format(b)
				self._logger.error('Unknown error detected:{0}'.format(errorMessage))
			
		else:
			self.Settings.debug.LogError("Failed to retrieve the snapshot module!  It might work again later.")

	
	##~~ AssetPlugin mixin
	def get_assets(self):
		self._logger.info("Octolapse is loading assets.")
		# Define your plugin's asset files to automatically include in the
		# core UI here.
		return dict(js = ["js/octolapse.js"],
			css = ["css/octolapse.css"],
			less = ["less/octolapse.less"])

	##~~ Softwareupdate hook
	def get_update_information(self):
		# Define the configuration for your plugin to use with the Software Update
		# Plugin here.  See
		# https://github.com/foosel/OctoPrint/wiki/Plugin:-Software-Update
		# for details.
		self._logger.info("Octolapse is geting update information.")
		return dict(octolapse = dict(displayName="Octolapse Plugin",
				displayVersion=self._plugin_version,
				# version check: github repository
				type="github_release",
				user="FormerLurker",
				repo="Octolapse",
				current=self._plugin_version,
				# update method: pip
				pip="https://github.com/FormerLurker/Octolapse/archive/{target_version}.zip"))

# If you want your plugin to be registered within OctoPrint under a different
# name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here.  Same goes for the
# other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties.  See the
# documentation for that.
__plugin_name__ = "Octolapse Plugin"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = OctolapsePlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.GcodeQueuing,
		"octoprint.comm.protocol.gcode.sent": __plugin_implementation__.GcodeSent,
		"octoprint.comm.protocol.gcode.received": __plugin_implementation__.GcodeReceived,

	}
