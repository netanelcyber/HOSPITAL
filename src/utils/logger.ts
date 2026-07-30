import pino from 'pino';
import { config } from '../config';

const pinoLogger = pino({
  level: config.environment === 'production' ? 'info' : 'debug',
  transport: {
    target: 'pino-pretty',
    options: {
      colorize: true,
      singleLine: false,
      translateTime: 'SYS:standard',
    },
  },
});

export class Logger {
  info(msg: string, meta?: any) {
    pinoLogger.info({ ...meta }, msg);
  }

  error(msg: string, error?: any) {
    pinoLogger.error({ err: error }, msg);
  }

  debug(msg: string, meta?: any) {
    pinoLogger.debug({ ...meta }, msg);
  }

  warn(msg: string, meta?: any) {
    pinoLogger.warn({ ...meta }, msg);
  }
}
