# logging stuff, code mostly uses getLogger()
import logging

# https://stackoverflow.com/questions/2183233/how-to-add-a-custom-loglevel-to-pythons-logging-facility
logging_trace_level = 5
logging.addLevelName(logging_trace_level, 'TRACE')

def getLogger(name):
    global root_logger
    log = root_logger.getChild(name)
    def trace(message, *args, **kws):
        if log.isEnabledFor(logging_trace_level):
            log._log(logging_trace_level, message, args, **kws)
    log.trace = trace
    return log

def registerLogging(level=logging.INFO):
    global root_logger, root_logger_formatter, root_logger_stream_handler, root_logger_file_handler, root_logger_operator_report_handler
    root_logger = logging.getLogger('z64import')
    root_logger_stream_handler = logging.StreamHandler()
    root_logger_file_handler = None
    root_logger_operator_report_handler = None
    root_logger_formatter = logging.Formatter('%(levelname)s:%(name)s: %(message)s')
    root_logger_stream_handler.setFormatter(root_logger_formatter)
    root_logger.addHandler(root_logger_stream_handler)
    root_logger.setLevel(1) # actual level filtering is left to handlers
    root_logger_stream_handler.setLevel(level)
    getLogger('setupLogging').debug('Logging OK')

def setLoggingLevel(level):
    global root_logger_stream_handler
    root_logger_stream_handler.setLevel(level)

def setLogFile(path):
    global root_logger, root_logger_formatter, root_logger_file_handler
    if root_logger_file_handler:
        root_logger.removeHandler(root_logger_file_handler)
        root_logger_file_handler = None
    if path:
        root_logger_file_handler = logging.FileHandler(path, mode='w')
        root_logger_file_handler.setFormatter(root_logger_formatter)
        root_logger.addHandler(root_logger_file_handler)
        root_logger_file_handler.setLevel(1)

class OperatorReportLogHandler(logging.Handler):
    def __init__(self, operator):
        super().__init__()
        self.operator = operator

    def flush(self):
        pass

    def emit(self, record):
        try:
            type = 'DEBUG'
            for levelType,  minLevel in (
                ('ERROR',   logging.WARNING), # comment to allow calling bpy.ops.file.zobj2020 without RuntimeError (makes WARNING the highest report level instead of ERROR)
                ('WARNING', logging.INFO),
                ('INFO',    logging.DEBUG)
            ):
                if record.levelno > minLevel:
                    type = levelType
                    break
            msg = self.format(record)
            self.operator.report({type}, msg)
        except Exception:
            self.handleError(record)

def setLogOperator(operator, level=logging.INFO):
    global root_logger, root_logger_formatter, root_logger_operator_report_handler
    if root_logger_operator_report_handler:
        root_logger.removeHandler(root_logger_operator_report_handler)
        root_logger_operator_report_handler = None
    if operator:
        root_logger_operator_report_handler = OperatorReportLogHandler(operator)
        root_logger_operator_report_handler.setFormatter(root_logger_formatter)
        root_logger_operator_report_handler.setLevel(level)
        root_logger.addHandler(root_logger_operator_report_handler)

def unregisterLogging():
    global root_logger, root_logger_stream_handler
    setLogFile(None)
    setLogOperator(None)
    root_logger.removeHandler(root_logger_stream_handler)
