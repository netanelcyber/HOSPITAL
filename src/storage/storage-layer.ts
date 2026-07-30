import AWS from 'aws-sdk';
import { config } from '../config';
import { Logger } from '../utils/logger';

const logger = new Logger();

export interface StorageObject {
  key: string;
  buffer: Buffer;
  metadata?: Record<string, any>;
}

export interface ReplicationConfig {
  nodes: string[];
  strategy: 'full' | 'sharded' | 'cached';
}

class DistributedStorageLayer {
  private s3Client: AWS.S3;
  private replicationConfig: ReplicationConfig;
  private nodeCache: Map<string, any> = new Map();

  constructor() {
    this.s3Client = new AWS.S3({
      endpoint: config.storage.s3.endpoint,
      accessKeyId: config.storage.s3.accessKey,
      secretAccessKey: config.storage.s3.secretKey,
      s3ForcePathStyle: true,
      region: config.storage.s3.region,
    });

    this.replicationConfig = {
      nodes: (process.env.STORAGE_NODES || 'node1,node2,node3').split(','),
      strategy: (process.env.REPLICATION_STRATEGY as any) || 'full',
    };
  }

  async initialize() {
    logger.info('Initializing distributed storage layer');

    // Ensure bucket exists
    try {
      await this.s3Client.headBucket({ Bucket: config.storage.s3.bucket }).promise();
      logger.info(`Storage bucket ${config.storage.s3.bucket} exists`);
    } catch (error: any) {
      if (error.code === 'NoSuchBucket') {
        logger.info(`Creating storage bucket ${config.storage.s3.bucket}`);
        await this.s3Client
          .createBucket({ Bucket: config.storage.s3.bucket })
          .promise();

        // Enable versioning
        await this.s3Client
          .putBucketVersioning({
            Bucket: config.storage.s3.bucket,
            VersioningConfiguration: { Status: 'Enabled' },
          })
          .promise();
      } else {
        throw error;
      }
    }

    logger.info('Storage layer initialized with strategy: ' + this.replicationConfig.strategy);
  }

  async upload(key: string, buffer: Buffer, metadata?: Record<string, any>): Promise<string> {
    logger.debug(`Uploading ${key} (${buffer.length} bytes)`);

    const params: AWS.S3.PutObjectRequest = {
      Bucket: config.storage.s3.bucket,
      Key: key,
      Body: buffer,
      Metadata: metadata,
      ContentType: metadata?.contentType || 'application/octet-stream',
    };

    try {
      const result = await this.s3Client.putObject(params).promise();
      logger.info(`Successfully uploaded ${key}`);

      // Trigger replication based on strategy
      if (this.replicationConfig.strategy === 'full') {
        await this.replicateToNodes(key, buffer, metadata);
      }

      return key;
    } catch (error) {
      logger.error(`Upload failed for ${key}`, error);
      throw error;
    }
  }

  async download(key: string): Promise<Buffer> {
    logger.debug(`Downloading ${key}`);

    try {
      const result = await this.s3Client
        .getObject({ Bucket: config.storage.s3.bucket, Key: key })
        .promise();

      if (result.Body) {
        const buffer = Buffer.isBuffer(result.Body)
          ? result.Body
          : Buffer.from(result.Body as any);
        logger.debug(`Successfully downloaded ${key} (${buffer.length} bytes)`);
        return buffer;
      }

      throw new Error('No data returned');
    } catch (error) {
      logger.error(`Download failed for ${key}`, error);
      throw error;
    }
  }

  async delete(key: string): Promise<void> {
    logger.debug(`Deleting ${key}`);

    try {
      await this.s3Client
        .deleteObject({ Bucket: config.storage.s3.bucket, Key: key })
        .promise();
      logger.info(`Successfully deleted ${key}`);

      // Trigger deletion replication
      if (this.replicationConfig.strategy === 'full') {
        await this.replicateDeletionToNodes(key);
      }
    } catch (error) {
      logger.error(`Delete failed for ${key}`, error);
      throw error;
    }
  }

  async exists(key: string): Promise<boolean> {
    try {
      await this.s3Client
        .headObject({ Bucket: config.storage.s3.bucket, Key: key })
        .promise();
      return true;
    } catch (error: any) {
      if (error.code === 'NotFound') {
        return false;
      }
      throw error;
    }
  }

  async getMetadata(key: string): Promise<Record<string, any>> {
    try {
      const result = await this.s3Client
        .headObject({ Bucket: config.storage.s3.bucket, Key: key })
        .promise();

      return {
        size: result.ContentLength,
        lastModified: result.LastModified,
        contentType: result.ContentType,
        metadata: result.Metadata,
        versionId: result.VersionId,
      };
    } catch (error) {
      logger.error(`Failed to get metadata for ${key}`, error);
      throw error;
    }
  }

  async listVersions(key: string): Promise<any[]> {
    try {
      const result = await this.s3Client
        .listObjectVersions({
          Bucket: config.storage.s3.bucket,
          Prefix: key,
        })
        .promise();

      return (result.Versions || []).map((v) => ({
        versionId: v.VersionId,
        lastModified: v.LastModified,
        size: v.Size,
      }));
    } catch (error) {
      logger.error(`Failed to list versions for ${key}`, error);
      throw error;
    }
  }

  async downloadVersion(key: string, versionId: string): Promise<Buffer> {
    try {
      const result = await this.s3Client
        .getObject({
          Bucket: config.storage.s3.bucket,
          Key: key,
          VersionId: versionId,
        })
        .promise();

      if (result.Body) {
        return Buffer.isBuffer(result.Body)
          ? result.Body
          : Buffer.from(result.Body as any);
      }

      throw new Error('No data returned');
    } catch (error) {
      logger.error(`Failed to download version ${versionId} of ${key}`, error);
      throw error;
    }
  }

  private async replicateToNodes(
    key: string,
    buffer: Buffer,
    metadata?: Record<string, any>
  ) {
    // In a real distributed system, this would replicate to other nodes
    // For now, we'll simulate it by caching
    for (const node of this.replicationConfig.nodes) {
      this.nodeCache.set(`${node}:${key}`, {
        buffer,
        metadata,
        timestamp: Date.now(),
      });
    }
    logger.debug(`Replicated ${key} to ${this.replicationConfig.nodes.length} nodes`);
  }

  private async replicateDeletionToNodes(key: string) {
    for (const node of this.replicationConfig.nodes) {
      this.nodeCache.delete(`${node}:${key}`);
    }
    logger.debug(`Replicated deletion of ${key} to ${this.replicationConfig.nodes.length} nodes`);
  }

  getReplicationStats() {
    return {
      strategy: this.replicationConfig.strategy,
      nodes: this.replicationConfig.nodes,
      cachedItems: this.nodeCache.size,
    };
  }
}

let storageLayer: DistributedStorageLayer;

export async function setupStorageLayer(): Promise<DistributedStorageLayer> {
  storageLayer = new DistributedStorageLayer();
  await storageLayer.initialize();
  return storageLayer;
}

export function getStorageLayer(): DistributedStorageLayer {
  if (!storageLayer) {
    throw new Error('Storage layer not initialized');
  }
  return storageLayer;
}
