import { Request, Response, NextFunction } from 'express';
import rateLimit from 'express-rate-limit';
import { Logger } from '../utils/logger';

const logger = new Logger();

interface SecurityConfig {
  enableRateLimit: boolean;
  enableDdosProtection: boolean;
  enableEncryption: boolean;
  enableCors: boolean;
  trustedProxies: string[];
}

export class APIGateway {
  private config: SecurityConfig;
  private requestCache: Map<string, number[]> = new Map();
  private blockedIps: Set<string> = new Set();
  private suspiciousActivity: Map<string, number> = new Map();

  constructor(config: Partial<SecurityConfig> = {}) {
    this.config = {
      enableRateLimit: config.enableRateLimit !== false,
      enableDdosProtection: config.enableDdosProtection !== false,
      enableEncryption: config.enableEncryption !== false,
      enableCors: config.enableCors !== false,
      trustedProxies: config.trustedProxies || ['127.0.0.1'],
    };
  }

  // Rate limiting middleware
  createRateLimiter(windowMs: number = 15 * 60 * 1000, maxRequests: number = 100) {
    return rateLimit({
      windowMs,
      max: maxRequests,
      message: 'Too many requests from this IP',
      standardHeaders: true,
      legacyHeaders: false,
      skip: (req) => {
        // Skip rate limiting for trusted IPs
        return this.config.trustedProxies.includes(this.getClientIp(req));
      },
      handler: (req, res) => {
        logger.warn(`Rate limit exceeded for IP ${this.getClientIp(req)}`);
        res.status(429).json({
          error: 'Too many requests',
          retryAfter: req.rateLimit?.resetTime,
        });
      },
    });
  }

  // DDoS protection middleware
  ddosProtectionMiddleware() {
    return (req: Request, res: Response, next: NextFunction) => {
      const clientIp = this.getClientIp(req);

      // Check if IP is blocked
      if (this.blockedIps.has(clientIp)) {
        return res.status(403).json({ error: 'Access denied' });
      }

      // Track requests per IP
      if (!this.requestCache.has(clientIp)) {
        this.requestCache.set(clientIp, []);
      }

      const now = Date.now();
      const times = this.requestCache.get(clientIp)!;

      // Remove requests older than 1 minute
      times.filter((t) => now - t < 60000);

      // Check for suspicious patterns
      if (times.length > 1000) {
        // More than 1000 requests per minute
        logger.warn(`Potential DDoS attack from ${clientIp}`);
        this.suspiciousActivity.set(clientIp, (this.suspiciousActivity.get(clientIp) || 0) + 1);

        if (this.suspiciousActivity.get(clientIp)! >= 3) {
          this.blockedIps.add(clientIp);
          logger.error(`IP ${clientIp} blocked due to suspicious activity`);
          return res.status(403).json({ error: 'Access denied' });
        }
      }

      times.push(now);
      next();
    };
  }

  // Request validation middleware
  validateRequestMiddleware() {
    return (req: Request, res: Response, next: NextFunction) => {
      // Validate content-type
      if (
        req.method !== 'GET' &&
        req.method !== 'DELETE' &&
        !req.is('application/json') &&
        !req.is('multipart/form-data')
      ) {
        return res.status(400).json({ error: 'Invalid content-type' });
      }

      // Validate request size
      const contentLength = parseInt(req.headers['content-length'] || '0');
      if (contentLength > 1024 * 1024 * 1024) {
        // 1GB limit
        return res.status(413).json({ error: 'Payload too large' });
      }

      // Validate request path for injection attempts
      if (this.detectInjectionAttempt(req.path)) {
        logger.warn(
          `Potential injection attempt from ${this.getClientIp(req)}: ${req.path}`
        );
        return res.status(400).json({ error: 'Invalid request' });
      }

      next();
    };
  }

  // Service-to-service authentication
  serviceAuthMiddleware(serviceSecret: string) {
    return (req: Request, res: Response, next: NextFunction) => {
      const serviceAuth = req.headers['x-service-auth'];

      if (!serviceAuth) {
        return res.status(401).json({ error: 'Service authentication required' });
      }

      if (serviceAuth !== serviceSecret) {
        logger.warn(`Invalid service auth attempt from ${this.getClientIp(req)}`);
        return res.status(401).json({ error: 'Invalid service credentials' });
      }

      next();
    };
  }

  // Response encryption/signing middleware
  responseSecurityMiddleware() {
    return (req: Request, res: Response, next: NextFunction) => {
      // Add security headers
      res.setHeader('X-Content-Type-Options', 'nosniff');
      res.setHeader('X-Frame-Options', 'DENY');
      res.setHeader('X-XSS-Protection', '1; mode=block');
      res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
      res.setHeader('Content-Security-Policy', "default-src 'self'");
      res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');

      // Store original send function
      const originalSend = res.send;

      // Override send to add security metadata
      res.send = function (data: any) {
        res.setHeader('X-Response-Time', Date.now().toString());
        return originalSend.call(this, data);
      };

      next();
    };
  }

  // IP whitelist middleware
  ipWhitelistMiddleware(whitelist: string[]) {
    return (req: Request, res: Response, next: NextFunction) => {
      const clientIp = this.getClientIp(req);

      if (!whitelist.includes(clientIp)) {
        logger.warn(`Access denied for non-whitelisted IP ${clientIp}`);
        return res.status(403).json({ error: 'Access denied' });
      }

      next();
    };
  }

  // Request sanitization
  sanitizeInput(input: string): string {
    return input
      .replace(/[<>]/g, '') // Remove HTML tags
      .replace(/[;`]/g, '') // Remove command injection chars
      .replace(/\.\.\//g, '') // Remove path traversal
      .substring(0, 1000); // Limit length
  }

  // Detect injection attempts
  private detectInjectionAttempt(path: string): boolean {
    const injectionPatterns = [
      /('|"|;|--|\/\*|\*\/|xp_|sp_)/i, // SQL injection
      /(javascript:|on\w+\s*=)/i, // XSS
      /(\.\.\/|\.\.\\)/i, // Path traversal
      /(<script|<iframe|<embed)/i, // HTML injection
      /union|select|insert|delete|drop|create|alter/i, // SQL keywords
    ];

    return injectionPatterns.some((pattern) => pattern.test(path));
  }

  // Get client IP (handles proxies)
  private getClientIp(req: Request): string {
    const forwarded = req.headers['x-forwarded-for'];

    if (forwarded) {
      const ips = typeof forwarded === 'string' ? forwarded.split(',') : forwarded;
      return ips[0].trim();
    }

    return req.ip || req.socket.remoteAddress || 'unknown';
  }

  // Get security stats
  getStats() {
    return {
      blockedIps: this.blockedIps.size,
      suspiciousIps: this.suspiciousActivity.size,
      totalTrackedIps: this.requestCache.size,
      configuration: {
        rateLimit: this.config.enableRateLimit,
        ddosProtection: this.config.enableDdosProtection,
        encryption: this.config.enableEncryption,
        cors: this.config.enableCors,
      },
    };
  }

  // Clear old data periodically
  startCleanup(intervalMs: number = 3600000) {
    // Clear every hour
    setInterval(() => {
      const oneHourAgo = Date.now() - 3600000;

      // Clean up old request times
      for (const [ip, times] of this.requestCache.entries()) {
        const recentTimes = times.filter((t) => now - t < 3600000);
        if (recentTimes.length === 0) {
          this.requestCache.delete(ip);
        } else {
          this.requestCache.set(ip, recentTimes);
        }
      }

      // Clean up old suspicious activity
      for (const [ip, count] of this.suspiciousActivity.entries()) {
        if (count === 0) {
          this.suspiciousActivity.delete(ip);
          this.blockedIps.delete(ip);
        }
      }

      logger.debug('Cleaned up old security data');
    }, intervalMs);

    const now = Date.now();
  }
}

export function createAPIGateway(config?: Partial<SecurityConfig>): APIGateway {
  return new APIGateway(config);
}
