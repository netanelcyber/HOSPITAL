import { Router, Request, Response } from 'express';
import bcrypt from 'bcrypt';
import jwt from 'jsonwebtoken';
import { v4 as uuidv4 } from 'uuid';
import { query } from '../db/postgres';
import { config } from '../config';
import { Logger } from '../utils/logger';
import { ActiveDirectoryService } from '../enterprise/active-directory';

const logger = new Logger();
export const authRoutes = Router();

let adService: ActiveDirectoryService | null = null;

if (config.activeDirectory.enabled && config.activeDirectory.serverUrl) {
  adService = new ActiveDirectoryService(config.activeDirectory as any);
}

authRoutes.post('/register', async (req: Request, res: Response) => {
  try {
    const { username, email, password, fullName } = req.body;

    if (!username || !email || !password) {
      return res.status(400).json({ error: 'Missing required fields' });
    }

    const passwordHash = await bcrypt.hash(password, 10);

    const result = await query(
      `INSERT INTO users (username, email, password_hash, full_name, role, status)
       VALUES ($1, $2, $3, $4, $5, $6)
       RETURNING id, username, email, role`,
      [username, email, passwordHash, fullName || '', 'user', 'active']
    );

    const user = result.rows[0];

    const token = jwt.sign(
      {
        id: user.id,
        username: user.username,
        email: user.email,
        role: user.role,
      },
      config.jwt.secret,
      { expiresIn: config.jwt.expiresIn }
    );

    logger.info(`User registered: ${username}`);

    res.status(201).json({
      user,
      token,
    });
  } catch (error: any) {
    logger.error('Registration error', error);

    if (error.code === '23505') {
      // Unique constraint violation
      return res.status(409).json({ error: 'Username or email already exists' });
    }

    res.status(500).json({ error: 'Registration failed' });
  }
});

authRoutes.post('/login', async (req: Request, res: Response) => {
  try {
    const { username, password } = req.body;

    if (!username || !password) {
      return res.status(400).json({ error: 'Missing username or password' });
    }

    let user: any = null;
    let adUser: any = null;

    if (adService) {
      try {
        adUser = await adService.authenticateUser(username, password);
        if (adUser) {
          logger.info(`User authenticated via Active Directory: ${username}`);

          try {
            const dbResult = await query(
              `SELECT id, role FROM users WHERE username = $1`,
              [username]
            );

            if (dbResult.rows.length > 0) {
              user = {
                id: dbResult.rows[0].id,
                username: adUser.username,
                email: adUser.email,
                role: dbResult.rows[0].role,
              };

              const userGroups = await adService.getUserGroups(username);
              const adRoles = adUser.roles || [];

              await query(
                `UPDATE users SET email = $1, full_name = $2, status = 'active'
                 WHERE id = $3`,
                [adUser.email, adUser.fullName, user.id]
              );
            } else {
              const userId = uuidv4();
              const adRoles = adUser.roles || ['user'];
              const primaryRole = adRoles[0] || 'user';

              await query(
                `INSERT INTO users (id, username, email, full_name, role, status, password_hash)
                 VALUES ($1, $2, $3, $4, $5, $6, $7)`,
                [userId, adUser.username, adUser.email, adUser.fullName, primaryRole, 'active', '']
              );

              user = {
                id: userId,
                username: adUser.username,
                email: adUser.email,
                role: primaryRole,
              };

              logger.info(`New user created from AD: ${username}`);
            }
          } catch (dbError) {
            logger.error('Failed to sync AD user to database', dbError);
            if (!config.activeDirectory.allowLocal) {
              return res.status(500).json({ error: 'Login failed' });
            }
          }
        }
      } catch (adError) {
        logger.debug('Active Directory authentication failed', adError);
        if (!config.activeDirectory.allowLocal) {
          return res.status(401).json({ error: 'Invalid credentials' });
        }
      }
    }

    if (!user) {
      const result = await query(
        `SELECT id, username, email, password_hash, role, status
         FROM users
         WHERE username = $1 AND status = 'active'`,
        [username]
      );

      if (result.rows.length === 0) {
        return res.status(401).json({ error: 'Invalid credentials' });
      }

      const dbUser = result.rows[0];
      const passwordValid = await bcrypt.compare(password, dbUser.password_hash);

      if (!passwordValid) {
        return res.status(401).json({ error: 'Invalid credentials' });
      }

      user = {
        id: dbUser.id,
        username: dbUser.username,
        email: dbUser.email,
        role: dbUser.role,
      };

      logger.info(`User logged in from local database: ${username}`);
    }

    const token = jwt.sign(
      {
        id: user.id,
        username: user.username,
        email: user.email,
        role: user.role,
      },
      config.jwt.secret,
      { expiresIn: config.jwt.expiresIn }
    );

    res.json({
      user: {
        id: user.id,
        username: user.username,
        email: user.email,
        role: user.role,
        source: adUser ? 'active_directory' : 'local',
      },
      token,
    });
  } catch (error) {
    logger.error('Login error', error);
    res.status(500).json({ error: 'Login failed' });
  }
});

authRoutes.post('/refresh', (req: Request, res: Response) => {
  try {
    const { token } = req.body;

    if (!token) {
      return res.status(400).json({ error: 'Token required' });
    }

    const decoded = jwt.verify(token, config.jwt.secret, {
      ignoreExpiration: true,
    }) as any;

    const newToken = jwt.sign(
      {
        id: decoded.id,
        username: decoded.username,
        email: decoded.email,
        role: decoded.role,
      },
      config.jwt.secret,
      { expiresIn: config.jwt.expiresIn }
    );

    res.json({ token: newToken });
  } catch (error) {
    logger.error('Token refresh error', error);
    res.status(401).json({ error: 'Invalid token' });
  }
});

authRoutes.get('/ad/status', (req: Request, res: Response) => {
  if (!adService) {
    return res.status(404).json({ error: 'Active Directory not enabled' });
  }

  try {
    const status = adService.getStatus();
    res.json(status);
  } catch (error) {
    logger.error('Failed to get AD status', error);
    res.status(500).json({ error: 'Failed to get AD status' });
  }
});

authRoutes.get('/ad/groups/:username', async (req: Request, res: Response) => {
  if (!adService) {
    return res.status(404).json({ error: 'Active Directory not enabled' });
  }

  try {
    const { username } = req.params;
    const groups = await adService.getUserGroups(username);
    res.json({ username, groups });
  } catch (error) {
    logger.error(`Failed to get groups for ${req.params.username}`, error);
    res.status(500).json({ error: 'Failed to get user groups' });
  }
});
