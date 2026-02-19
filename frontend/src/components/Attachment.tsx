/**
 * Attachment components for image uploads.
 *
 * Gives Rosemary eyes! Allows pasting/dragging images into the composer.
 */

import { FC } from "react";
import {
  ComposerPrimitive,
  MessagePrimitive,
  AttachmentPrimitive,
  useAttachment,
} from "@assistant-ui/react";
import { Paperclip, X, ImageIcon } from "lucide-react";

// -----------------------------------------------------------------------------
// Composer attachment (with remove button)
// -----------------------------------------------------------------------------

const ComposerAttachment: FC = () => {
  const attachment = useAttachment();

  // Try to get image URL from the attachment
  let imageUrl: string | undefined;
  if (attachment.type === "image") {
    // For pending attachments, we might have a file we can preview
    if ("file" in attachment && attachment.file) {
      imageUrl = URL.createObjectURL(attachment.file);
    }
    // For complete attachments, check content
    if ("content" in attachment && attachment.content) {
      const imageContent = attachment.content.find(
        (c): c is { type: "image"; image: string } => c.type === "image"
      );
      if (imageContent) {
        imageUrl = imageContent.image;
      }
    }
  }

  return (
    <AttachmentPrimitive.Root className="relative w-16 h-16 rounded-lg overflow-hidden bg-surface border border-border">
      {imageUrl ? (
        <img
          src={imageUrl}
          alt={attachment.name}
          className="w-full h-full object-cover"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-muted">
          <ImageIcon size={24} />
        </div>
      )}
      <AttachmentPrimitive.Remove className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-primary border-none flex items-center justify-center cursor-pointer text-white">
        <X size={12} />
      </AttachmentPrimitive.Remove>
    </AttachmentPrimitive.Root>
  );
};

// -----------------------------------------------------------------------------
// ComposerAttachments — renders all pending attachments
// -----------------------------------------------------------------------------

export const ComposerAttachments: FC = () => {
  return (
    <ComposerPrimitive.Attachments
      components={{ Attachment: ComposerAttachment }}
    />
  );
};

// -----------------------------------------------------------------------------
// ComposerAddAttachment — the "+" button to add images
// -----------------------------------------------------------------------------

export const ComposerAddAttachment: FC = () => {
  return (
    <ComposerPrimitive.AddAttachment
      className="w-9 h-9 flex items-center justify-center bg-transparent border border-border rounded-lg text-muted cursor-pointer"
      title="Add image"
    >
      <Paperclip size={18} />
    </ComposerPrimitive.AddAttachment>
  );
};

// -----------------------------------------------------------------------------
// UserMessageAttachments — renders attachments in sent messages
// -----------------------------------------------------------------------------

const MessageAttachment: FC = () => {
  const attachment = useAttachment();

  // Get image URL from attachment content
  let imageUrl: string | undefined;
  if (attachment.type === "image" && "content" in attachment && attachment.content) {
    const imageContent = attachment.content.find(
      (c): c is { type: "image"; image: string } => c.type === "image"
    );
    if (imageContent) {
      imageUrl = imageContent.image;
    }
  }

  return (
    <div className="w-30 h-30 rounded-lg overflow-hidden bg-surface border border-border">
      {imageUrl ? (
        <img
          src={imageUrl}
          alt={attachment.name}
          className="w-full h-full object-cover"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-muted">
          <ImageIcon size={32} />
        </div>
      )}
    </div>
  );
};

export const UserMessageAttachments: FC = () => {
  return (
    <div className="flex flex-wrap gap-2 mb-2">
      <MessagePrimitive.Attachments
        components={{ Attachment: MessageAttachment }}
      />
    </div>
  );
};
