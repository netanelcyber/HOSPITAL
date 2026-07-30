import { createClient } from 'redis';
import { config } from '../config';
import { Logger } from '../utils/logger';

const logger = new Logger();

export let redisClient: ReturnType<typeof createClient>;

export async function setupRedis() {
  redisClient = createClient({
    host: config.redis.host,
    port: config.redis.port,
    password: config.redis.password,
    socket: {
      reconnectStrategy: (retries) => Math.min(retries * 50, 500),
    },
  });

  redisClient.on('error', (err) => {
    logger.error('Redis client error', err);
  });

  redisClient.on('connect', () => {
    logger.info('Redis client connected');
  });

  await redisClient.connect();
  logger.info('Redis cache initialized');
}

export async function cacheGet(key: string): Promise<any> {
  try {
    const value = await redisClient.get(key);
    if (value) {
      return JSON.parse(value);
    }
    return null;
  } catch (error) {
    logger.warn('Cache get error', error);
    return null;
  }
}

export async function cacheSet(key: string, value: any, ttl: number = 3600) {
  try {
    await redisClient.setEx(key, ttl, JSON.stringify(value));
  } catch (error) {
    logger.warn('Cache set error', error);
  }
}

export async function cacheDelete(key: string) {
  try {
    await redisClient.del(key);
  } catch (error) {
    logger.warn('Cache delete error', error);
  }
}

export async function cacheInvalidatePattern(pattern: string) {
  try {
    const keys = await redisClient.keys(pattern);
    if (keys.length > 0) {
      await redisClient.del(keys);
    }
  } catch (error) {
    logger.warn('Cache pattern invalidation error', error);
  }
}
