-- Create database
CREATE DATABASE IF NOT EXISTS vi_auto;
USE vi_auto;

-- Create campaigns table
CREATE TABLE IF NOT EXISTS campaigns (
    id INT(11) NOT NULL AUTO_INCREMENT,
    campaign_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_records INT(11) DEFAULT 0,
    total_users INT(11) DEFAULT 0,
    duplicate_num_per_batch INT(11) DEFAULT 0,
    duplicate_num_per_day INT(11) DEFAULT 0,
    status ENUM('ongoing', 'completed', 'paused') DEFAULT 'ongoing',
    PRIMARY KEY (id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id INT(11) NOT NULL AUTO_INCREMENT,
    campaign_id INT(11) NOT NULL,
    mobile VARCHAR(15) NOT NULL,
    circle_name VARCHAR(10),
    current_balance DECIMAL(10,2) NOT NULL,
    validity_dt DATE NOT NULL,
    validity_in_days INT(11) NOT NULL,
    status ENUM('pending', 'processing', 'processed', 'failed') DEFAULT 'pending',
    worker_id VARCHAR(50),
    processing_started_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_campaign_id (campaign_id),
    INDEX idx_mobile (mobile),
    INDEX idx_circle_name (circle_name),
    INDEX idx_validity_in_days (validity_in_days),
    INDEX idx_status (status),
    INDEX idx_worker_id (worker_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create videos_table
CREATE TABLE IF NOT EXISTS videos_table (
    id INT(11) NOT NULL AUTO_INCREMENT,
    users_id INT(11) NOT NULL,
    video_public_url VARCHAR(500) NOT NULL,
    generation_status ENUM('pending', 'completed', 'failed') DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_users_id (users_id),
    INDEX idx_generation_status (generation_status),
    FOREIGN KEY (users_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create logging_table
CREATE TABLE IF NOT EXISTS logging_table (
    id INT(11) NOT NULL AUTO_INCREMENT,
    campaign_id INT(11) NOT NULL,
    users_id INT(11) NOT NULL,
    video_id INT(11) NOT NULL,
    delivery_status ENUM('sent', 'failed', 'pending') DEFAULT 'pending',
    sent_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_campaign_id (campaign_id),
    INDEX idx_users_id (users_id),
    INDEX idx_video_id (video_id),
    INDEX idx_delivery_status (delivery_status),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (users_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (video_id) REFERENCES videos_table(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
