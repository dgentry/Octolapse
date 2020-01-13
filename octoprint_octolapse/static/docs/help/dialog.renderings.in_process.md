This dialog shows the progress of any renderings that are in the rendering queue.  Timelapses will be rendered in the order they are sent, and go through three phases:

1.  Pending - These timelapses have not yet started the rendering process.
2.  Pre-Rendering - The pre-rendering phase includes several operations that need to be performed before the ffmpeg/avconv can run.  First, snapshots are copied from the temporary snapshot folder to the temporary rendering folder and converted to jpg files if necessary (this can take quite a while).  Next, any scripts configured within the **Before Render Script** camera settings for the current camera is executed.  After this, any snapshot metadata that exists is read and stored.  After this, Octolapse ensures there are enough images to render a timelapse (at least two images are required).  Finally the FPS is calculated for the final timelapse.
3.  Rendering - Text overlays are added first, if they are configured within your rendering settings.  Next, pre and post roll is added if configured.  Then the timelapse is rendered via ffmpeg/avconv.  After this, any scripts configured within the **After Render Script** camera settings for the current camera is executed.  Next, the snapshots are archived based on the **Archive Snapshots After Rendering** setting in the rendering profile.  Finally the temporary rendering directory is cleaned.