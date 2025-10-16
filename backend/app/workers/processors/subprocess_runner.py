# app/workers/processors/subprocess_runner.py - ENHANCED VERSION
import subprocess
import logging
import sys
import os
import time
from typing import Optional
from dotenv import load_dotenv

# Load environment
load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create console handler if not already present
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] [SUBPROCESS] [%(levelname)s] %(message)s")
    )
    logger.addHandler(handler)


def start_campaign_processing(campaign_id: str, user_id: str) -> bool:
    """
    Start campaign processing in a separate process.

    This function launches the campaign processor as a subprocess,
    allowing the API to return immediately while processing happens
    in the background.

    Args:
        campaign_id: UUID of campaign to process
        user_id: UUID of campaign owner

    Returns:
        bool: True if subprocess started successfully, False otherwise
    """

    try:
        logger.info(f"🚀 Starting campaign processor subprocess")
        logger.info(f"Campaign ID: {campaign_id}")
        logger.info(f"User ID: {user_id}")

        # Get the path to campaign_processor.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        processor_path = os.path.join(current_dir, "campaign_processor.py")

        logger.info(f"Current directory: {current_dir}")
        logger.info(f"Looking for processor at: {processor_path}")

        if not os.path.exists(processor_path):
            logger.error(f"❌ Processor script not found: {processor_path}")

            # List files in directory for debugging
            try:
                files = os.listdir(current_dir)
                logger.info(f"Files in {current_dir}: {files}")
            except Exception as e:
                logger.error(f"Could not list directory: {e}")

            return False

        logger.info(f"✅ Processor script found: {processor_path}")

        # Ensure the processor file is executable/readable
        try:
            with open(processor_path, "r") as f:
                first_line = f.readline()
                logger.info(f"Processor file first line: {first_line.strip()}")
        except Exception as e:
            logger.error(f"❌ Cannot read processor file: {e}")
            return False

        # Build command
        command = [
            sys.executable,  # Use current Python interpreter
            processor_path,
            campaign_id,
            user_id,
        ]

        logger.info(f"Command to execute: {' '.join(command)}")
        logger.info(f"Python executable: {sys.executable}")
        logger.info(f"Working directory: {os.getcwd()}")

        # Prepare environment
        env = os.environ.copy()

        # Ensure PYTHONPATH includes the app directory
        app_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = f"{app_root}{os.pathsep}{env['PYTHONPATH']}"
        else:
            env["PYTHONPATH"] = app_root

        logger.info(f"App root directory: {app_root}")
        logger.info(f"PYTHONPATH: {env.get('PYTHONPATH', 'Not set')}")

        # Start subprocess in detached mode
        logger.info("🔄 Starting subprocess...")

        if sys.platform == "win32":
            # Windows: use CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                env=env,
                cwd=app_root,  # Set working directory
            )
        else:
            # Unix: use preexec_fn
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setpgrp if hasattr(os, "setpgrp") else None,
                env=env,
                cwd=app_root,  # Set working directory
            )

        process_id = process.pid
        logger.info(f"✅ Processor subprocess started (PID: {process_id})")

        # Wait a short time to catch immediate errors
        try:
            # Poll the process to see if it's still running
            time.sleep(1)  # Give it a moment to start
            return_code = process.poll()

            if return_code is not None:
                # Process has already exited
                stdout, stderr = process.communicate()
                stdout_str = stdout.decode() if stdout else ""
                stderr_str = stderr.decode() if stderr else ""

                logger.error(f"❌ Processor exited immediately with code {return_code}")
                if stdout_str:
                    logger.error(f"STDOUT: {stdout_str}")
                if stderr_str:
                    logger.error(f"STDERR: {stderr_str}")
                return False
            else:
                # Process is still running
                logger.info(f"✅ Processor running in background (PID: {process_id})")

                # Optionally, create a log file to track the process
                try:
                    log_file = os.path.join(
                        current_dir, f"campaign_{campaign_id[:8]}.pid"
                    )
                    with open(log_file, "w") as f:
                        f.write(str(process_id))
                    logger.info(f"PID written to: {log_file}")
                except Exception as e:
                    logger.warning(f"Could not write PID file: {e}")

                return True

        except Exception as e:
            logger.error(f"❌ Error checking subprocess status: {e}")
            return False

    except FileNotFoundError as e:
        logger.error(f"❌ Python executable not found: {e}")
        return False
    except PermissionError as e:
        logger.error(f"❌ Permission denied: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to start processor: {e}", exc_info=True)
        return False


def check_processor_status(campaign_id: str) -> dict:
    """
    Check if a processor is still running for a given campaign.

    Args:
        campaign_id: UUID of campaign to check

    Returns:
        dict: Status information about the processor
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        pid_file = os.path.join(current_dir, f"campaign_{campaign_id[:8]}.pid")

        if not os.path.exists(pid_file):
            return {"running": False, "message": "No PID file found"}

        with open(pid_file, "r") as f:
            pid = int(f.read().strip())

        # Check if process is still running
        try:
            os.kill(pid, 0)  # Send signal 0 to check if process exists
            return {"running": True, "pid": pid, "message": f"Process {pid} is running"}
        except OSError:
            # Process not running, clean up PID file
            os.remove(pid_file)
            return {"running": False, "message": f"Process {pid} has stopped"}

    except Exception as e:
        return {"running": False, "message": f"Error checking status: {e}"}


def stop_processor(campaign_id: str) -> dict:
    """
    Stop a running processor for a given campaign.

    Args:
        campaign_id: UUID of campaign to stop

    Returns:
        dict: Result of stop operation
    """
    try:
        status = check_processor_status(campaign_id)

        if not status["running"]:
            return {"success": True, "message": "Processor not running"}

        pid = status.get("pid")
        if not pid:
            return {"success": False, "message": "Could not get PID"}

        # Terminate the process
        try:
            if sys.platform == "win32":
                import signal

                os.kill(pid, signal.SIGTERM)
            else:
                os.kill(pid, 15)  # SIGTERM

            time.sleep(2)  # Give it time to terminate gracefully

            # Check if it's still running
            try:
                os.kill(pid, 0)
                # Still running, force kill
                if sys.platform == "win32":
                    os.kill(pid, signal.SIGKILL)
                else:
                    os.kill(pid, 9)  # SIGKILL
            except OSError:
                pass  # Process has stopped

            # Clean up PID file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            pid_file = os.path.join(current_dir, f"campaign_{campaign_id[:8]}.pid")
            if os.path.exists(pid_file):
                os.remove(pid_file)

            return {"success": True, "message": f"Processor {pid} stopped"}

        except Exception as e:
            return {"success": False, "message": f"Failed to stop process: {e}"}

    except Exception as e:
        return {"success": False, "message": f"Error stopping processor: {e}"}
